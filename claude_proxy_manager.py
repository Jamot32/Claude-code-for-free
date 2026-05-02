import os
import json
import yaml
import subprocess
import signal
import sys
import shutil
from pathlib import Path
from dotenv import load_dotenv, set_key
import customtkinter as ctk
from tkinter import messagebox

# Configuration and Constants
APP_NAME = "Claude Code Proxy Manager"
CLAUDE_CONFIG_DIR = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / ".claude"
CLAUDE_SETTINGS_FILE = CLAUDE_CONFIG_DIR / "settings.json"
CLAUDE_BACKUP_FILE = CLAUDE_CONFIG_DIR / "settings.json.backup"
# Use a fixed absolute directory so litellm always finds config regardless of CWD
PROXY_DATA_DIR = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / ".claude-nvidia"
ENV_FILE = PROXY_DATA_DIR / "nvidia.env"
LITELLM_CONFIG_FILE = PROXY_DATA_DIR / "config.yaml"

NVIDIA_MODELS = [
    "nvidia_nim/mistralai/mistral-large-3-675b-instruct-2512",
    "nvidia_nim/z-ai/glm4.7",
    "nvidia_nim/minimaxai/minimax-m2.7",
    "nvidia_nim/qwen/qwen3-coder-480b-a35b-instruct",
    "nvidia_nim/google/gemma-3n-e4b-it"
]

class ClaudeProxyApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Window Setup
        self.title(APP_NAME)
        self.geometry("750x700")
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # State
        self.proxy_process = None
        self.is_proxy_on = False
        self.load_env_vars()

        # UI Components
        self.setup_ui()
        self.check_initial_state()

    def load_env_vars(self):
        PROXY_DATA_DIR.mkdir(parents=True, exist_ok=True)
        if ENV_FILE.exists():
            load_dotenv(ENV_FILE)
        else:
            ENV_FILE.touch()

    def setup_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.tabview = ctk.CTkTabview(self, corner_radius=15)
        self.tabview.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        
        self.tabview.add("Proxy Manager")
        self.tabview.add("Model Support")
        self.tabview.set("Proxy Manager")

        # --- Proxy Manager Tab ---
        self.main_frame = self.tabview.tab("Proxy Manager")
        self.main_frame.grid_columnconfigure(0, weight=1)

        # Title
        self.title_label = ctk.CTkLabel(self.main_frame, text=APP_NAME, font=ctk.CTkFont(size=24, weight="bold"))
        self.title_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        # API Key Section
        self.api_key_label = ctk.CTkLabel(self.main_frame, text="NVIDIA API Key:", font=ctk.CTkFont(size=14))
        self.api_key_label.grid(row=1, column=0, padx=20, pady=(10, 0), sticky="w")
        
        self.api_key_entry = ctk.CTkEntry(self.main_frame, placeholder_text="nvapi-...", show="*", width=400)
        self.api_key_entry.grid(row=2, column=0, padx=20, pady=(5, 10), sticky="ew")
        self.api_key_entry.insert(0, os.getenv("NVIDIA_API_KEY", ""))

        # Model Selector Section
        self.model_label = ctk.CTkLabel(self.main_frame, text="Select NVIDIA NIM Model:", font=ctk.CTkFont(size=14))
        self.model_label.grid(row=3, column=0, padx=20, pady=(10, 0), sticky="w")
        
        self.model_var = ctk.StringVar(value=NVIDIA_MODELS[0])
        self.model_dropdown = ctk.CTkOptionMenu(self.main_frame, values=NVIDIA_MODELS, variable=self.model_var, width=400)
        self.model_dropdown.grid(row=4, column=0, padx=20, pady=(5, 10), sticky="ew")

        # Advanced Options
        self.adv_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.adv_frame.grid(row=5, column=0, padx=20, pady=5, sticky="ew")
        
        self.disable_tools_var = ctk.BooleanVar(value=False)
        self.disable_tools_check = ctk.CTkCheckBox(self.adv_frame, text="Disable Tool Calling", variable=self.disable_tools_var)
        self.disable_tools_check.grid(row=0, column=0, padx=5, pady=5)

        self.check_models_btn = ctk.CTkButton(self.adv_frame, text="Check Model Support", command=self.check_nvidia_models, width=150)
        self.check_models_btn.grid(row=0, column=1, padx=5, pady=5)

        self.test_tool_btn = ctk.CTkButton(self.adv_frame, text="Test Tool Calling", command=self.test_tool_calling, width=150)
        self.test_tool_btn.grid(row=0, column=2, padx=5, pady=5)

        # Toggle Section
        self.toggle_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.toggle_frame.grid(row=6, column=0, padx=20, pady=10)

        self.status_indicator = ctk.CTkLabel(self.toggle_frame, text="●", text_color="gray", font=ctk.CTkFont(size=20))
        self.status_indicator.grid(row=0, column=0, padx=5)

        self.status_text = ctk.CTkLabel(self.toggle_frame, text="Proxy: OFF", font=ctk.CTkFont(size=16, weight="bold"))
        self.status_text.grid(row=0, column=1, padx=5)

        self.master_switch = ctk.CTkSwitch(self.toggle_frame, text="", command=self.toggle_proxy)
        self.master_switch.grid(row=0, column=2, padx=10)

        # Log/Info Section
        self.info_box = ctk.CTkTextbox(self.main_frame, height=120, font=ctk.CTkFont(size=12))
        self.info_box.grid(row=7, column=0, padx=20, pady=10, sticky="ew")
        self.info_box.insert("0.0", "Welcome! Enter your API key and toggle the switch to start.\n'Check Model Support' will fetch and show all available NIMs.")
        self.info_box.configure(state="disabled")

        # --- Model Support Tab ---
        self.models_tab = self.tabview.tab("Model Support")
        self.models_tab.grid_columnconfigure(0, weight=1)
        self.models_tab.grid_rowconfigure(2, weight=1)

        self.model_search_var = ctk.StringVar()
        self.model_search_var.trace_add("write", lambda *args: self.update_models_display())
        
        search_frame = ctk.CTkFrame(self.models_tab, fg_color="transparent")
        search_frame.grid(row=0, column=0, padx=20, pady=(20, 5), sticky="ew")
        search_frame.grid_columnconfigure(0, weight=1)

        self.model_search_entry = ctk.CTkEntry(search_frame, placeholder_text="Search models (e.g. llama, mistral, qwen)...", textvariable=self.model_search_var)
        self.model_search_entry.grid(row=0, column=0, padx=(0, 10), sticky="ew")

        self.refresh_models_btn = ctk.CTkButton(search_frame, text="Refresh List", width=100, command=self.check_nvidia_models)
        self.refresh_models_btn.grid(row=0, column=1)

        # Filter Frame
        self.filter_frame = ctk.CTkFrame(self.models_tab, fg_color="transparent")
        self.filter_frame.grid(row=1, column=0, padx=20, pady=(0, 10), sticky="ew")
        
        self.code_only_var = ctk.BooleanVar(value=False)
        self.code_only_check = ctk.CTkCheckBox(self.filter_frame, text="Code", variable=self.code_only_var, command=self.update_models_display, width=60)
        self.code_only_check.pack(side="left", padx=5)
        
        self.free_only_var = ctk.BooleanVar(value=False)
        self.free_only_check = ctk.CTkCheckBox(self.filter_frame, text="Free", variable=self.free_only_var, command=self.update_models_display, width=60)
        self.free_only_check.pack(side="left", padx=5)

        self.reasoning_var = ctk.BooleanVar(value=False)
        self.reasoning_check = ctk.CTkCheckBox(self.filter_frame, text="Reasoning", variable=self.reasoning_var, command=self.update_models_display, width=90)
        self.reasoning_check.pack(side="left", padx=5)

        self.tools_var = ctk.BooleanVar(value=False)
        self.tools_check = ctk.CTkCheckBox(self.filter_frame, text="Tools/Agent", variable=self.tools_var, command=self.update_models_display, width=100)
        self.tools_check.pack(side="left", padx=5)

        self.long_context_var = ctk.BooleanVar(value=False)
        self.long_context_check = ctk.CTkCheckBox(self.filter_frame, text="Long Ctx", variable=self.long_context_var, command=self.update_models_display, width=90)
        self.long_context_check.pack(side="left", padx=5)

        self.models_scroll = ctk.CTkScrollableFrame(self.models_tab, label_text="Available NVIDIA NIM Models")
        self.models_scroll.grid(row=2, column=0, padx=20, pady=(0, 20), sticky="nsew")
        
        self.supported_models_list = []
        self.model_item_frames = []
        
        # Initial empty state message
        self.empty_lbl = ctk.CTkLabel(self.models_scroll, text="Click 'Refresh List' or 'Check Model Support' to fetch models.", font=ctk.CTkFont(slant="italic"))
        self.empty_lbl.pack(pady=40)

    def test_tool_calling(self):
        api_key = self.api_key_entry.get().strip()
        model = self.model_var.get().replace("nvidia_nim/", "")
        if not api_key:
            messagebox.showerror("Error", "Please enter an API key first.")
            return

        def run_test():
            try:
                self.log(f"Testing tool calling for {model}...")
                import requests
                test_payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": "What is the weather in London? Use the get_weather tool."}],
                    "tools": [{
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "parameters": {
                                "type": "object",
                                "properties": {"location": {"type": "string"}}
                            }
                        }
                    }],
                    "tool_choice": "auto"
                }
                response = requests.post(
                    "https://integrate.api.nvidia.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=test_payload
                )
                if response.status_code == 200:
                    data = response.json()
                    message = data.get("choices", [{}])[0].get("message", {})
                    if "tool_calls" in message:
                        self.log("✅ SUCCESS: Model supports tool calling!")
                    else:
                        self.log("⚠️ PARTIAL: Model responded but did NOT use the tool.")
                elif response.status_code == 400:
                    err = response.json().get("error", {}).get("message", "")
                    if "tool choice" in err.lower() or "tool_call_parser" in err.lower():
                        self.log("❌ FAILED: Backend requires specific flags (not supported).")
                    else:
                        self.log(f"❌ FAILED: 400 Bad Request: {err[:50]}...")
                else:
                    self.log(f"❌ ERROR: Status {response.status_code}")
            except Exception as e:
                self.log(f"Test error: {str(e)}")

        import threading
        threading.Thread(target=run_test, daemon=True).start()

    def check_nvidia_models(self):
        api_key = self.api_key_entry.get().strip()
        if not api_key:
            messagebox.showerror("Error", "Please enter an API key first.")
            self.tabview.set("Proxy Manager")
            return
        
        def run_check():
            try:
                self.log("Fetching available models from NVIDIA...")
                import requests
                response = requests.get(
                    "https://integrate.api.nvidia.com/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"}
                )
                if response.status_code == 200:
                    models = response.json().get("data", [])
                    self.supported_models_list = sorted([m.get("id") for m in models])
                    self.log(f"Success! Found {len(self.supported_models_list)} models.")
                    
                    # Update UI on main thread
                    self.after(0, self.update_models_display)
                    self.after(100, lambda: self.tabview.set("Model Support"))
                else:
                    self.log(f"Failed to fetch models: {response.status_code}")
                    self.log(response.text[:100])
            except Exception as e:
                self.log(f"Error checking models: {str(e)}")

        import threading
        threading.Thread(target=run_check, daemon=True).start()

    def update_models_display(self):
        # Clear existing
        if hasattr(self, 'empty_lbl') and self.empty_lbl:
            self.empty_lbl.destroy()
            self.empty_lbl = None

        for frame in self.model_item_frames:
            frame.destroy()
        self.model_item_frames = []

        query = self.model_search_var.get().lower()
        code_only = self.code_only_var.get()
        free_only = self.free_only_var.get()
        reason_only = self.reasoning_var.get()
        tools_only = self.tools_var.get()
        long_only = self.long_context_var.get()

        filtered = []
        for mid in self.supported_models_list:
            mid_lower = mid.lower()
            
            # Text search filter
            if query and query not in mid_lower:
                continue
                
            # Code models filter
            if code_only:
                code_keywords = ['code', 'coder', 'codestral', 'codegemma', 'starcoder', 'dracarys']
                if not any(k in mid_lower for k in code_keywords): continue
            
            # Free endpoints filter
            if free_only:
                free_keywords = ['8b', '7b', '2b', 'instruct', 'nemotron-nano', 'small', 'phi-3', 'phi-4']
                if not any(k in mid_lower for k in free_keywords): continue

            # Reasoning filter
            if reason_only:
                reason_keywords = ['thinking', 'reason', 'r1', 'v3', 'logic', 'chain']
                if not any(k in mid_lower for k in reason_keywords): continue

            # Tools/Agentic filter
            if tools_only:
                tool_keywords = ['tool', 'agent', 'function', 'chatqa', 'nemoguard']
                if not any(k in mid_lower for k in tool_keywords): continue

            # Long Context filter
            if long_only:
                long_keywords = ['128k', '256k', '512k', '1m', 'long', 'context']
                if not any(k in mid_lower for k in long_keywords): continue
                    
            filtered.append(mid)


        for mid in filtered:
            item_frame = ctk.CTkFrame(self.models_scroll, fg_color="transparent")
            item_frame.pack(fill="x", padx=5, pady=2)
            
            lbl = ctk.CTkLabel(item_frame, text=mid, anchor="w", font=ctk.CTkFont(size=12))
            lbl.pack(side="left", padx=10, fill="x", expand=True)
            
            # Use button
            use_btn = ctk.CTkButton(item_frame, text="Use", width=60, height=24, 
                                    command=lambda m=mid: self.select_model(m))
            use_btn.pack(side="right", padx=5)
            
            self.model_item_frames.append(item_frame)

    def select_model(self, model_id):
        # Identify capabilities for the "Model Card" labels
        mid_lower = model_id.lower()
        capabilities = []
        if any(k in mid_lower for k in ['code', 'coder', 'codestral', 'codegemma', 'starcoder', 'dracarys']):
            capabilities.append(("CODE", "#1f538d"))
        if any(k in mid_lower for k in ['8b', '7b', '2b', 'instruct', 'nemotron-nano', 'small', 'phi-3', 'phi-4']):
            capabilities.append(("FREE", "#2fa572"))
        if any(k in mid_lower for k in ['thinking', 'reason', 'r1', 'v3', 'logic', 'chain']):
            capabilities.append(("LOGIC", "#a652bb"))
        if any(k in mid_lower for k in ['tool', 'agent', 'function', 'chatqa', 'nemoguard']):
            capabilities.append(("TOOLS", "#e28743"))
        if any(k in mid_lower for k in ['128k', '256k', '512k', '1m', 'long', 'context']):
            capabilities.append(("LONG", "#33a1c9"))

        # Create custom confirmation dialog
        conf_win = ctk.CTkToplevel(self)
        conf_win.title("Model Details")
        conf_win.geometry("550x450") # Slightly larger
        conf_win.attributes("-topmost", True)
        conf_win.grid_columnconfigure(0, weight=1)
        
        # Make it modal
        conf_win.grab_set()
        
        # Center window logic
        self.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() // 2) - 275
        y = self.winfo_y() + (self.winfo_height() // 2) - 225
        conf_win.geometry(f"+{x}+{y}")

        # Model Card Container
        card = ctk.CTkFrame(conf_win, corner_radius=15, border_width=2, border_color="#3d3d3d")
        card.pack(fill="both", expand=True, padx=20, pady=20)
        
        ctk.CTkLabel(card, text="NVIDIA NIM MODEL CARD", font=ctk.CTkFont(size=10, weight="bold"), text_color="#888888").pack(pady=(20, 10))
        
        model_name = model_id.split('/')[-1]
        ctk.CTkLabel(card, text=model_name, font=ctk.CTkFont(size=24, weight="bold"), text_color="white").pack(pady=5)
        ctk.CTkLabel(card, text=model_id, font=ctk.CTkFont(size=11), text_color="#aaaaaa").pack(pady=(0, 20))
        
        # Capability Chips
        chip_frame = ctk.CTkFrame(card, fg_color="transparent")
        chip_frame.pack(pady=10)
        
        if not capabilities:
            ctk.CTkLabel(chip_frame, text="GENERAL PURPOSE", font=ctk.CTkFont(size=9, weight="bold"), 
                         fg_color="#3d3d3d", text_color="white", corner_radius=10, padx=10, pady=4).pack(side="left")
        else:
            for tag, color in capabilities:
                t = ctk.CTkLabel(chip_frame, text=tag, font=ctk.CTkFont(size=9, weight="bold"), 
                                 fg_color=color, text_color="white", corner_radius=10, padx=10, pady=4)
                t.pack(side="left", padx=4)
            
        desc_text = "This model is compatible with Claude Code. Ensure your API key has sufficient credits if not using a free-tier model."
        ctk.CTkLabel(card, text=desc_text, font=ctk.CTkFont(size=13), wraplength=400, text_color="#dddddd").pack(pady=20, padx=30)
        
        # Action Buttons
        btn_frame = ctk.CTkFrame(card, fg_color="transparent")
        btn_frame.pack(pady=(0, 25), side="bottom")
        
        def confirm():
            full_id = f"nvidia_nim/{model_id}"
            global NVIDIA_MODELS
            if full_id not in NVIDIA_MODELS:
                NVIDIA_MODELS.append(full_id)
                self.model_dropdown.configure(values=NVIDIA_MODELS)
            self.model_var.set(full_id)
            self.tabview.set("Proxy Manager")
            self.log(f"Switched model to {model_id}")
            conf_win.destroy()

        ctk.CTkButton(btn_frame, text="Confirm Selection", command=confirm, width=160, height=40, font=ctk.CTkFont(weight="bold"),
                      fg_color="#1f538d", hover_color="#14375e").pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="Go Back", command=conf_win.destroy, width=100, height=40, 
                      fg_color="transparent", border_width=1, border_color="#555555").pack(side="left", padx=10)

    def log(self, message):
        self.info_box.configure(state="normal")
        self.info_box.insert("end", f"\n> {message}")
        self.info_box.see("end")
        self.info_box.configure(state="disabled")

    def check_initial_state(self):
        # Check if Claude config is already pointing to proxy
        if CLAUDE_SETTINGS_FILE.exists():
            try:
                with open(CLAUDE_SETTINGS_FILE, 'r') as f:
                    config = json.load(f)
                    if config.get("env", {}).get("ANTHROPIC_BASE_URL") == "http://localhost:4000":
                        self.log("Detected existing proxy configuration.")
                        # We don't automatically turn it ON because the process isn't running
            except Exception as e:
                self.log(f"Error reading Claude config: {e}")

    def save_api_key(self):
        api_key = self.api_key_entry.get().strip()
        if not api_key:
            messagebox.showwarning("Warning", "Please enter an NVIDIA API Key.")
            return False
        set_key(str(ENV_FILE), "NVIDIA_API_KEY", api_key)
        os.environ["NVIDIA_API_KEY"] = api_key
        return True

    def generate_litellm_config(self, selected_model):
        drop_list = ["output_config"]
        if self.disable_tools_var.get():
            drop_list.extend(["tools", "tool_choice"])
            self.log("Configured to DROP tools (disables agentic features)")

        config = {
            "litellm_settings": {
                "drop_params": True,
                "additional_drop_params": drop_list,
                "enable_auto_tool_choice": True,
                "tool_call_parser": "llama3" # Supports tool calling for non-native models
            },
            "model_list": [
                {
                    "model_name": "*",
                    "litellm_params": {
                        "model": selected_model,
                        "api_base": "https://integrate.api.nvidia.com/v1",
                        "api_key": "os.environ/NVIDIA_API_KEY"
                    }
                }
            ]
        }
        with open(LITELLM_CONFIG_FILE, 'w') as f:
            yaml.dump(config, f)

    def modify_claude_config(self, enable=True):
        if not CLAUDE_CONFIG_DIR.exists():
            CLAUDE_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        if enable:
            # Backup existing
            if CLAUDE_SETTINGS_FILE.exists() and not CLAUDE_BACKUP_FILE.exists():
                shutil.copy2(CLAUDE_SETTINGS_FILE, CLAUDE_BACKUP_FILE)
                self.log("Created backup of Claude settings.")
            
            # Write proxy settings — ANTHROPIC_BASE_URL redirects Claude Code to litellm
            # ANTHROPIC_AUTH_TOKEN overrides the claude.ai OAuth token with a dummy value
            # (the real NVIDIA API key is in config.yaml, not here)
            # ANTHROPIC_MODEL tells Claude Code which model to request (litellm wildcard routes it)
            selected_model = self.model_var.get()
            # Strip the nvidia_nim/ prefix to get just the model name Claude Code will request
            model_display = selected_model.replace("nvidia_nim/", "")
            proxy_settings = {
                "env": {
                    "ANTHROPIC_BASE_URL": "http://localhost:4000",
                    "ANTHROPIC_AUTH_TOKEN": "dummy-key-for-litellm-proxy",
                    "ANTHROPIC_MODEL": model_display,
                    "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1"
                }
            }
            with open(CLAUDE_SETTINGS_FILE, 'w') as f:
                json.dump(proxy_settings, f, indent=2)
            self.log(f"Claude settings updated (model: {model_display}, betas disabled)")
        else:
            # Restore from backup
            if CLAUDE_BACKUP_FILE.exists():
                shutil.move(CLAUDE_BACKUP_FILE, CLAUDE_SETTINGS_FILE)
                self.log("Restored Claude settings from backup.")
            elif CLAUDE_SETTINGS_FILE.exists():
                # If no backup but file exists, it might be our proxy file
                try:
                    with open(CLAUDE_SETTINGS_FILE, 'r') as f:
                        config = json.load(f)
                        if config.get("env", {}).get("ANTHROPIC_BASE_URL") == "http://localhost:4000":
                            os.remove(CLAUDE_SETTINGS_FILE)
                            self.log("Removed proxy settings. Claude will use defaults.")
                except:
                    pass

    def toggle_proxy(self):
        if self.master_switch.get() == 1:
            self.start_proxy()
        else:
            self.stop_proxy()

    def start_proxy(self):
        if not self.save_api_key():
            self.master_switch.deselect()
            return

        selected_model = self.model_var.get()
        self.log(f"Starting proxy with model: {selected_model}")
        
        try:
            self.generate_litellm_config(selected_model)
            self.modify_claude_config(enable=True)

            # Launch LiteLLM in a VISIBLE new console window
            cmd = [
                "litellm", 
                "--config", str(LITELLM_CONFIG_FILE), 
                "--port", "4000"
            ]
            
            if sys.platform == "win32":
                self.proxy_process = subprocess.Popen(
                    cmd,
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
            else:
                self.proxy_process = subprocess.Popen(cmd)

            self.log("LiteLLM window opened. Waiting for proxy to be ready...")
            self.api_key_entry.configure(state="disabled")
            self.model_dropdown.configure(state="disabled")

            # Poll health endpoint until ready (max 30s)
            self.after(2000, self._check_proxy_ready, 0)

        except FileNotFoundError:
            self.log("ERROR: 'litellm' command not found. Run: pip install 'litellm[proxy]'")
            self.modify_claude_config(enable=False)
            self.master_switch.deselect()
            messagebox.showerror("Error", "litellm not found.\nRun: pip install 'litellm[proxy]'")
        except Exception as e:
            self.log(f"Error starting proxy: {e}")
            self.stop_proxy()
            messagebox.showerror("Error", f"Failed to start proxy: {e}")

    def _check_proxy_ready(self, attempts):
        """Poll localhost:4000/health until litellm is ready or we give up."""
        import urllib.request
        import urllib.error

        # Check if the process already died
        if self.proxy_process and self.proxy_process.poll() is not None:
            self.log("ERROR: LiteLLM exited immediately. Check the console window for errors.")
            self.stop_proxy()
            messagebox.showerror("Error", "LiteLLM failed to start.\nCheck the opened console window for details.")
            return

        try:
            urllib.request.urlopen("http://localhost:4000/health", timeout=2)
            # Success — proxy is up
            self.is_proxy_on = True
            self.status_indicator.configure(text_color="green")
            self.status_text.configure(text="Proxy: ON (NVIDIA NIM)")
            self.log("✓ Proxy ready! Now restart Claude Code to use NVIDIA NIM.")
        except Exception:
            if attempts < 15:  # retry up to 15 times (30s total)
                self.log(f"Waiting for proxy... ({attempts + 1}/15)")
                self.after(2000, self._check_proxy_ready, attempts + 1)
            else:
                self.log("ERROR: Proxy did not respond after 30s. Check the console window.")
                self.stop_proxy()
                messagebox.showerror("Error", "Proxy timed out.\nCheck the LiteLLM console window for errors.")

    def stop_proxy(self):
        self.log("Stopping proxy...")
        
        if self.proxy_process:
            try:
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proxy_process.pid)], capture_output=True)
                else:
                    os.kill(self.proxy_process.pid, signal.SIGTERM)
                self.proxy_process = None
            except Exception as e:
                self.log(f"Error killing process: {e}")

        self.modify_claude_config(enable=False)
        
        self.is_proxy_on = False
        self.status_indicator.configure(text_color="gray")
        self.status_text.configure(text="Proxy: OFF")
        self.master_switch.deselect()
        
        # Re-enable inputs
        self.api_key_entry.configure(state="normal")
        self.model_dropdown.configure(state="normal")
        self.log("Proxy stopped and settings restored.")

    def on_closing(self):
        if self.is_proxy_on:
            if messagebox.askokcancel("Quit", "Proxy is still running. Do you want to stop it and quit?"):
                self.stop_proxy()
                self.destroy()
        else:
            self.destroy()

if __name__ == "__main__":
    app = ClaudeProxyApp()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()
