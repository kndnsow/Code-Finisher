import tkinter as tk
from tkinter import (
    filedialog, messagebox, ttk, scrolledtext,
    StringVar, BooleanVar, Listbox, Menu, Text
)
import os
import re
import threading
import queue
import time
import difflib
import fnmatch
import sys
import traceback
import json
import xml.dom.minidom
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- Configuration Constants ---
SUPPORTED_EXTENSIONS = [
    ".py", ".c", ".h", ".html", ".css", ".scss", ".less", ".js", ".jsx", ".ts", ".tsx",
    ".php", ".cs", ".cpp", ".java", ".json", ".xml", ".yaml", ".yml", ".md"
]
# Default patterns to ignore during directory processing
DEFAULT_IGNORE_PATTERNS = [
    "*.log", "*.tmp", "*.bak", "*.swp", "*.pyc",
    "__pycache__/", "node_modules/", "vendor/",
    ".git/", ".svn/", ".hg/",
    "dist/", "build/", "target/",
    "*.min.js", "*.min.css"
]


# --- Helper Functions ---

def is_likely_binary(filepath):
    """Checks if a file is likely binary using simple heuristics."""
    try:
        with open(filepath, 'rb') as f:
            chunk = f.read(1024)
            if not chunk: return False
            if b'\0' in chunk: return True # Contains null byte
            # Check ratio of non-printable ASCII characters
            text_chars = bytes(range(32, 127)) + b'\n\r\t\f\b'
            nontext_ratio = sum(1 for byte in chunk if byte not in text_chars) / len(chunk)
            return nontext_ratio > 0.3 # Arbitrary threshold
    except Exception:
        return False # Assume text if reading fails
    return False

def normalize_eol(code, eol_sequence):
    """Converts all line endings to the specified sequence ('CRLF' or 'LF')."""
    if not isinstance(code, str): return code # Safety check
    # Normalize all to LF first
    normalized_code = code.replace('\r\n', '\n').replace('\r', '\n')
    # Convert to target EOL
    if eol_sequence == "CRLF":
        return normalized_code.replace('\n', '\r\n')
    # elif eol_sequence == "LF": # Implicitly LF if not CRLF
    return normalized_code
    # Default to LF if sequence is somehow invalid (though UI prevents this)
    # return normalized_code

def remove_comments_by_type(code, file_extension):
    """Removes comments based on typical language syntax using regex.

    Note: Regex-based removal has limitations and may fail on complex edge cases
          (e.g., comments within string literals that look like comments).
    """
    if not isinstance(code, str): return code # Safety check
    original_code = code
    try:
        if file_extension == ".py":
            # Remove full line # comments, consuming the newline if possible
            code = re.sub(r'^[ \t]*#.*?$\n?', '', code, flags=re.MULTILINE)
            # Remove trailing/inline comments (preceded by space)
            code = re.sub(r'(?m)\s+#.*$', '', code)

        elif file_extension in [".c", ".cpp", ".h", ".hpp", ".java", ".m", ".js", ".jsx", ".ts", ".tsx", ".cs", ".css", ".scss", ".less"]:
            # Remove block comments /* ... */ (non-greedy) first
            code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
            # Remove line comments // ..., consuming the newline if possible
            code = re.sub(r'//.*?$\n?', '', code, flags=re.MULTILINE)

        elif file_extension in [".html", ".xml"]:
            # Remove HTML/XML comments <!-- ... -->
            code = re.sub(r'<!--.*?-->', '', code, flags=re.DOTALL)

        elif file_extension == ".php":
            # Remove block comments /* ... */ first
            code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
            # Remove full line # comments, consuming newline
            code = re.sub(r'^[ \t]*#.*?$\n?', '', code, flags=re.MULTILINE)
            # Remove line // comments, consuming newline
            code = re.sub(r'//.*?$\n?', '', code, flags=re.MULTILINE)
            # Remove trailing # comments (preceded by space)
            code = re.sub(r'(?m)\s+#.*$', '', code)

        # Add rules for other comment styles if needed here

        return code # Return potentially modified code

    except Exception as e:
        print(f"Error removing comments (Regex likely - {file_extension}): {e}")
        return original_code # Return original if regex fails catastrophically

def remove_extra_empty_lines_smart(code):
    """Consolidates multiple blank lines into a single blank line."""
    if not isinstance(code, str): return code # Safety check
    if not code: return ""
    # Normalize line endings to \n for processing
    normalized_code = code.replace('\r\n', '\n').replace('\r', '\n')
    # Replace 2 or more consecutive newlines with exactly two newlines (\n\n)
    # This means max one empty line between content lines.
    # Also strip leading/trailing whitespace from the entire string FIRST
    # to handle potential whitespace lines correctly.
    cleaned_code = re.sub(r'\n{2,}', '\n\n', normalized_code.strip())
    return cleaned_code


def format_internal_basic(code_content, file_extension):
    """Provides basic internal pretty-printing for JSON and XML."""
    if not isinstance(code_content, str): return code_content, False # Safety check
    if file_extension == ".json":
        try:
            parsed = json.loads(code_content)
            # Use indent=2 for common style, sort keys for consistency
            formatted_code = json.dumps(parsed, indent=2, sort_keys=True)
            return formatted_code, True
        except Exception as e: # Catch JSONDecodeError and others
            print(f"Internal JSON format failed: {e}")
            return code_content, False # Return original on failure

    elif file_extension == ".xml":
        try:
            # Need to remove XML declaration manually if it exists, minidom adds it back
            code_no_decl = re.sub(r'<\?xml.*?\?>\s*', '', code_content, flags=re.IGNORECASE | re.DOTALL).strip()
            if not code_no_decl: return "", True # Handle empty after decl removal

            dom = xml.dom.minidom.parseString(code_no_decl)
            # toprettyxml adds declaration and potentially unwanted whitespace
            pretty_xml_with_decl = dom.toprettyxml(indent="  ")
            # Remove the declaration minidom adds
            pretty_xml_no_decl = re.sub(r'<\?xml.*?\?>\s*', '', pretty_xml_with_decl, flags=re.IGNORECASE | re.DOTALL).strip()
            # Remove blank lines potentially added by pretty printing
            cleaned_xml = '\n'.join(line for line in pretty_xml_no_decl.splitlines() if line.strip())
            return cleaned_xml, True
        except Exception as e: # Catch XML ParseError and others
            print(f"Internal XML format failed: {e}")
            return code_content, False # Return original on failure

    else:
        # No internal formatter for this file type
        return code_content, False


# --- Application Class ---
class CodeCleanerApp:
    """Main application class for the Code Cleaner."""

    def __init__(self, root):
        """Initialize the application."""
        self.root = root
        self.root.title("Code Cleaner")
        # Try to start maximized
        try: self.root.state('zoomed')
        except tk.TclError: # Fallback if 'zoomed' is not supported
            w, h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            self.root.geometry(f"{w}x{h}+0+0")
        icon_path = os.path.join(BASE_DIR, "icon.ico")
        self.root.iconbitmap(icon_path)
        # --- State Variables ---
        self.selected_paths = [] # Paths selected by user (file or dir)
        self.original_content = {} # Cache for original file content {filepath: content}
        self.processed_content = {} # Cache for processed content {filepath: content}
        self.current_eol = StringVar(value="CRLF") # User's choice for line ending
        self.remove_comments_var = BooleanVar(value=True)
        self.remove_empty_lines_var = BooleanVar(value=True)
        self.current_processing_file = StringVar(value="") # For status bar display
        # Use default ignore patterns, loaded into the UI text widget
        self.ignore_patterns = list(DEFAULT_IGNORE_PATTERNS)
        # Queue for communication between processing thread and UI thread
        self.ui_update_queue = queue.Queue()

        # --- Initialize UI Components ---
        self.style = ttk.Style()
        self._setup_menu_widgets()
        self._setup_ui_widgets()
        self._apply_dark_theme() # Apply fixed theme
        self._finalize_menu_setup()
        self._bind_events()      # Bind UI events
        self.listbox_path_map = {}
        self.processing_base_dir = None
        # Start queue checker loop
        self.check_queue()

    # --- UI Setup Methods ---

    def _setup_menu_widgets(self):
        """Creates the Menu widget objects (without commands/cascades)."""
        self.menubar = Menu(self.root, tearoff=0)
        self.file_menu = Menu(self.menubar, tearoff=0)
        self.edit_menu = Menu(self.menubar, tearoff=0)
        self.view_menu = Menu(self.menubar, tearoff=0)
        self.eol_submenu = Menu(self.view_menu, tearoff=0)

    def _setup_ui_widgets(self):
        """Creates and packs/grids the main UI widgets."""
        # Main Layout Frames
        # Control panel (fixed width on left)
        self.control_frame = ttk.Frame(self.root, padding=10, width=300)
        self.control_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(5, 2), pady=5)
        self.control_frame.pack_propagate(False) # Prevent shrinking

        # Status bar (bottom)
        self.status_frame = ttk.Frame(self.root, padding=(10, 5))
        self.status_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(0, 5), padx=(5, 5))

        # Preview panel (fills remaining space)
        self.preview_frame = ttk.Frame(self.root, padding=(5, 10, 10, 0))
        self.preview_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=(5, 0))

        # Populate Frames
        self._setup_control_panel_widgets()
        self._setup_preview_panel_widgets()
        self._setup_status_bar_widgets()

    def _setup_control_panel_widgets(self):
        """Creates widgets for the left control panel."""
        # Buttons
        ttk.Button(self.control_frame, text="Select File...", command=self._select_file).pack(pady=5, fill=tk.X)
        ttk.Button(self.control_frame, text="Select Directory...", command=self._select_directory).pack(pady=5, fill=tk.X)

        # Options Frame
        options_frame = ttk.LabelFrame(self.control_frame, text="Cleaning Options", padding="10")
        options_frame.pack(pady=10, fill=tk.X)
        ttk.Checkbutton(options_frame, text="Remove Comments", variable=self.remove_comments_var).pack(anchor=tk.W)
        ttk.Checkbutton(options_frame, text="Remove Extra Empty Lines", variable=self.remove_empty_lines_var).pack(anchor=tk.W)

        # Action Buttons
        self.process_button = ttk.Button(self.control_frame, text="Process Selected", command=self._start_processing_action)
        self.process_button.pack(pady=(15, 5), fill=tk.X, ipady=4)
        self.save_button = ttk.Button(self.control_frame, text="Save All Changes", command=self._save_all_changes_action, state=tk.DISABLED)
        self.save_button.pack(pady=5, fill=tk.X)
        self.undo_button = ttk.Button(self.control_frame, text="Undo All (Session)", command=self._undo_all_changes_action, state=tk.DISABLED)
        self.undo_button.pack(pady=5, fill=tk.X)

        # Processed Files List
        ttk.Label(self.control_frame, text="Processed Files:").pack(pady=(15, 0), anchor=tk.W)
        self.list_frame = ttk.Frame(self.control_frame) # Frame for Listbox + Scrollbar
        self.list_frame.pack(pady=5, fill=tk.BOTH, expand=True)
        self.file_listbox = Listbox(self.list_frame, height=8, relief=tk.FLAT, bd=0)
        file_list_scroll = ttk.Scrollbar(self.list_frame, orient=tk.VERTICAL, command=self.file_listbox.yview)
        self.file_listbox.config(yscrollcommand=file_list_scroll.set)
        file_list_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Ignore List
        ignore_frame_lf = ttk.LabelFrame(self.control_frame, text="Ignore Patterns (Glob)", padding=5)
        ignore_frame_lf.pack(pady=(10, 5), fill=tk.X)
        self.ignore_list_text = Text(ignore_frame_lf, height=4, wrap=tk.WORD, relief=tk.FLAT, bd=0)
        self.ignore_list_text.pack(fill=tk.X, expand=True, padx=3, pady=(0, 3))
        self.ignore_list_text.insert("1.0", "\n".join(self.ignore_patterns))

    def _setup_preview_panel_widgets(self):
        """Creates widgets for the preview area."""
        self.preview_label = ttk.Label(self.preview_frame, text="Preview: Select a file from the list", anchor=tk.W)
        self.preview_label.pack(pady=(0, 5), fill=tk.X)

        self.diff_frame = ttk.Frame(self.preview_frame)
        self.diff_frame.pack(fill=tk.BOTH, expand=True)
        self.diff_frame.grid_columnconfigure(0, weight=1)
        self.diff_frame.grid_columnconfigure(1, weight=1)
        self.diff_frame.grid_rowconfigure(1, weight=1) # Text areas expand

        self.before_title_label = ttk.Label(self.diff_frame, text="Before")
        self.before_title_label.grid(row=0, column=0, sticky="w", padx=5)
        self.after_title_label = ttk.Label(self.diff_frame, text="After")
        self.after_title_label.grid(row=0, column=1, sticky="w", padx=5)

        # Before Panel Frame and Text
        self.before_frame = ttk.Frame(self.diff_frame)
        self.before_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 2))
        self.before_text = scrolledtext.ScrolledText(self.before_frame, wrap=tk.NONE, state=tk.DISABLED, relief=tk.FLAT, bd=0)
        self.before_text.pack(fill=tk.BOTH, expand=True)

        # After Panel Frame and Text (Now Permanently Disabled)
        self.after_frame = ttk.Frame(self.diff_frame)
        self.after_frame.grid(row=1, column=1, sticky="nsew", padx=(2, 0))
        self.after_text = scrolledtext.ScrolledText(self.after_frame, wrap=tk.NONE, state=tk.DISABLED, relief=tk.FLAT, bd=0)
        self.after_text.pack(fill=tk.BOTH, expand=True)

        # Define diff tags (colors applied by theme)
        self.before_text.tag_config("difference")
        self.after_text.tag_config("difference")

    def _setup_status_bar_widgets(self):
        """Creates widgets for the bottom status bar."""
        self.status_frame.grid_columnconfigure(0, weight=1) # Status label expands
        self.status_label = ttk.Label(self.status_frame, text="Ready", anchor=tk.W)
        self.status_label.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        # Animation label (simple dots)
        self.loading_animation_label = ttk.Label(self.status_frame, text="", anchor=tk.W)
        self.loading_animation_label.grid(row=0, column=1, sticky='w')
        # Progress bar (right-aligned)
        self.progress_bar = ttk.Progressbar(self.status_frame, orient=tk.HORIZONTAL, length=200, mode='determinate')
        self.progress_bar.grid(row=0, column=2, sticky="e", padx=(10, 0))

    def _apply_dark_theme(self):
        """Applies the hardcoded dark theme styles to UI elements."""
        # Color definitions
        bg_color="#1e1e1e"; fg_color="#d4d4d4"; select_bg="#3a3d41"; select_fg="#ffffff";
        button_bg="#3a3d41"; button_fg="#ffffff"; text_bg="#252526"; text_fg="#cccccc";
        disabled_fg="#7f7f7f"; frame_bg="#252526"; frame_border="#444444"; diff_remove_bg="#6b2020";
        diff_add_bg="#206b20"; listbox_bg="#2a2d2e"; menu_bg="#2a2d2e";
        menu_active_bg="#3e6382"; menu_active_fg="#ffffff"
        try:
            self.style.theme_use('clam')
            # Configure TTK Styles
            self.style.configure('.', foreground=fg_color, background=frame_bg)
            self.style.configure('TButton', background=button_bg, foreground=button_fg, padding=5, borderwidth=0, focuscolor=select_fg, relief=tk.FLAT) # Flat buttons
            self.style.map('TButton', background=[('active', select_bg), ('disabled', frame_bg)], foreground=[('disabled', disabled_fg)])
            self.style.configure('TCheckbutton', background=frame_bg, foreground=fg_color, indicatorcolor=button_bg)
            self.style.map('TCheckbutton', indicatorcolor=[('selected', select_bg), ('active', select_bg)], foreground=[('disabled', disabled_fg)])
            self.style.configure('TLabel', background=frame_bg, foreground=fg_color)
            self.style.configure('TFrame', background=frame_bg)
            self.style.configure('TLabelframe', background=frame_bg, bordercolor=frame_border, relief=tk.FLAT, borderwidth=1) # Keep border maybe? or 0
            self.style.configure('TLabelframe.Label', background=frame_bg, foreground=fg_color)
            self.style.configure('TProgressbar', troughcolor=button_bg, background=select_bg, thickness=20)
            self.style.configure('TScrollbar', background=button_bg, troughcolor=frame_bg, arrowcolor=fg_color, relief=tk.FLAT, borderwidth=0)
            self.style.configure('Bg.TLabel', background=bg_color, foreground=fg_color)
            self.style.configure('Preview.TLabel', background=bg_color, foreground=disabled_fg)
            self.style.configure('Preview.TFrame', background=bg_color)

            # Configure Root and Standard Tk Widgets
            self.root.config(bg=bg_color)
            self.control_frame.configure(style='TFrame')
            self.status_frame.configure(style='TFrame')
            self.preview_frame.configure(style='Preview.TFrame')
            self.diff_frame.configure(style='Preview.TFrame')
            self.before_frame.configure(style='Preview.TFrame')
            self.after_frame.configure(style='Preview.TFrame')
            self.list_frame.configure(style='TFrame')

            # Listbox
            self.file_listbox.config(bg=listbox_bg, fg=fg_color, selectbackground=select_bg, selectforeground=select_fg, highlightthickness=0, relief=tk.FLAT, bd=0)
            # Ignore List Text
            self.ignore_list_text.config(bg=text_bg, fg=text_fg, insertbackground=fg_color, selectbackground=select_bg, selectforeground=select_fg, highlightthickness=0, relief=tk.FLAT, bd=0)
            # Preview Text Widgets
            text_opts = {"bg": text_bg, "fg": text_fg, "insertbackground": fg_color, "selectbackground": select_bg, "selectforeground": select_fg, "relief": tk.FLAT, "bd": 0, "font": ('Consolas', 10), "highlightthickness": 0}
            self.before_text.configure(**text_opts)
            self.after_text.configure(**text_opts)
            self.before_text.configure(state=tk.DISABLED) # Keep Before disabled
            self.after_text.configure(state=tk.DISABLED) # Keep After disabled too

            # Diff Tag Colors
            self.before_text.tag_config("difference", background=diff_remove_bg)
            self.after_text.tag_config("difference", background=diff_add_bg)

            # Labels (Ensure ttk styles applied)
            self.status_label.configure(style='TLabel')
            self.preview_label.configure(style='Preview.TLabel')
            self.loading_animation_label.configure(style='TLabel')
            self.before_title_label.configure(style='Bg.TLabel')
            self.after_title_label.configure(style='Bg.TLabel')

            # Configure Menus
            menu_opts = {"bg": menu_bg, "fg": fg_color, "relief": tk.FLAT, "bd": 0, "activebackground": menu_active_bg, "activeforeground": menu_active_fg, "activeborderwidth": 0, "disabledforeground": disabled_fg}
            try:
                # Apply config to all menu widgets
                for menu in [self.menubar, self.file_menu, self.edit_menu, self.view_menu, self.eol_submenu]:
                     menu.config(**menu_opts)
            except tk.TclError as e: print(f"Note: Menu styling may be limited by OS: {e}")

        except Exception as e: print(f"ERROR applying theme: {e}"); traceback.print_exc()


    def _finalize_menu_setup(self):
        """Adds commands/cascades to menus (after styling)."""
        self.root.config(menu=self.menubar)
        # File Menu
        self.menubar.add_cascade(label="File", menu=self.file_menu)
        self.file_menu.add_command(label="Select File...", command=self._select_file)
        self.file_menu.add_command(label="Select Directory...", command=self._select_directory)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Save All Changes", command=self._save_all_changes_action, state=tk.DISABLED)
        self.save_menu_item_idx = self.file_menu.index(tk.END)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Exit", command=self.root.quit)
        # Edit Menu
        self.menubar.add_cascade(label="Edit", menu=self.edit_menu)
        self.edit_menu.add_command(label="Undo All (Session)", command=self._undo_all_changes_action, state=tk.DISABLED)
        self.undo_menu_item_idx = self.edit_menu.index(tk.END)
        # View Menu (Simplified - only EOL)
        self.menubar.add_cascade(label="View", menu=self.view_menu)
        self.view_menu.add_cascade(label="EOL Sequence", menu=self.eol_submenu)
        self.eol_submenu.add_radiobutton(label="CRLF (Windows)", variable=self.current_eol, value="CRLF")
        self.eol_submenu.add_radiobutton(label="LF (Unix/Mac)", variable=self.current_eol, value="LF")

    def _bind_events(self):
        """Binds UI events to their handler methods."""
        self.file_listbox.bind('<<ListboxSelect>>', self._on_file_select)
        self.ignore_list_text.bind("<KeyRelease>", self._update_ignore_patterns)
        # No binding needed for after_text anymore

    # --- Event Handlers ---

    def _select_file(self):
        """Handles the 'Select File' action."""
        filepath = filedialog.askopenfilename(
            title="Select Code File",
            filetypes=[("Code Files", " ".join(SUPPORTED_EXTENSIONS)), ("All Files", "*.*")]
        )
        if filepath:
            self.selected_paths = [filepath]
            self.status_label.config(text=f"Selected: {os.path.basename(filepath)}")
            self._reset_ui_state()

    def _select_directory(self):
        """Handles the 'Select Directory' action."""
        dirpath = filedialog.askdirectory(title="Select Project Directory")
        if dirpath:
            self.selected_paths = [dirpath]
            self.status_label.config(text=f"Selected Dir: {os.path.basename(dirpath)}")
            self._reset_ui_state()

    def _start_processing_action(self):
        """Starts the file processing thread when 'Process Selected' is clicked."""
        if not self.selected_paths:
            messagebox.showwarning("No Selection", "Please select a file or directory first.")
            return
        self._reset_ui_state()
        # Gather options
        options = {
            "remove_comments": self.remove_comments_var.get(),
            "remove_empty_lines": self.remove_empty_lines_var.get(),
            "set_eol": self.current_eol.get(),
            "ignore": list(self.ignore_patterns) # Pass a copy
        }
        target = self.selected_paths[0]
        # Determine the base directory
        if os.path.isdir(target):
            self.processing_base_dir = target
        else:
            self.processing_base_dir = None # Signal single file selection

        # Start background thread
        thread = threading.Thread(
            target=self._processing_thread_worker,
            args=(target, options, self.processing_base_dir),  # Pass base_dir here
            daemon=True
        )
        thread.start()

    def _save_all_changes_action(self):
        """Handles the 'Save All Changes' action, prompting the user first."""
        files_to_save = list(self.processed_content.keys())
        if not files_to_save:
            messagebox.showinfo("No Changes", "No processed files available to save.")
            return

        if not messagebox.askyesno(
            "Confirm Save",
            f"This will OVERWRITE {len(files_to_save)} original file(s) with the cleaned version.\n\n"
            "MAKE SURE YOU HAVE BACKUPS if necessary!\n\nAre you absolutely sure?"
            ):
            return # User cancelled

        # Perform save (using _save_files internal method)
        self._save_files(files_to_save)


    def _undo_all_changes_action(self):
        """Handles the 'Undo All' action, reverting in-memory changes."""
        if not self.original_content:
            messagebox.showinfo("Nothing to Undo", "No original state saved from the last processing run.")
            return
        if not messagebox.askyesno(
            "Confirm Session Undo",
            "Revert all changes in the preview panes back to their state BEFORE the last 'Process Selected' was run?\n\n(This does NOT affect files already saved to disk)."
            ):
            return # User cancelled

        # Restore processed cache from original cache
        self.processed_content.clear()
        self.processed_content.update(self.original_content)
        # Clear original cache - Undo is now 'spent' for this processing run
        self.original_content.clear()

        # Refresh the preview if a file is selected
        if self._get_selected_filepath_from_listbox():
            self._on_file_select() # This will re-run diff (now showing no difference)
        else:
            self._update_preview_panes(None, None) # Clear preview if nothing selected

        self.status_label.config(text="Changes reverted in preview (Session Undo).")
        self._update_button_states() # Update buttons (Undo should now be disabled)

    def _on_file_select(self, event=None):
        """Updates preview panes when a file is selected in the listbox."""
        filepath = self._get_selected_filepath_from_listbox()
        # Note: After text is now permanently disabled, no need to manage its state here
        if not filepath:
            self.preview_label.config(text="Preview")
            self._update_preview_panes(None, None) # Clear preview
            return

        # Retrieve content from caches
        original_code, processed_code = self._get_content_from_cache(filepath)

        # Update label and panes
        self.preview_label.config(text=f"Preview: {os.path.basename(filepath)}")
        self._update_preview_panes(original_code, processed_code)


    def _update_ignore_patterns(self, event=None):
         """Reads ignore patterns from text widget and updates internal list."""
         self.ignore_patterns = [
             p.strip() for p in self.ignore_list_text.get("1.0", tk.END).splitlines() if p.strip()
         ]

    # --- Core Logic & Processing Methods ---

    def _processing_thread_worker(self, target_path, options, base_dir):
        """Background thread to process files/directories without freezing the UI."""
        files_to_process = []
        total_files_checked = 0
        if os.path.isdir(target_path):
            try:
                ignore_list = options.get("ignore", [])
                dir_ignore = [p.replace('/', '').replace('\\', '') for p in ignore_list if p.endswith(('/', '\\'))]
                file_ignore = [p for p in ignore_list if not p.endswith(('/', '\\'))]

                for root, dirs, files in os.walk(target_path, topdown=True):
                    # Filter ignored directories IN-PLACE
                    dirs[:] = [d for d in dirs if d not in dir_ignore]

                    for file in files:
                        total_files_checked += 1
                        filepath = os.path.join(root, file)
                        ext = os.path.splitext(file)[1].lower()
                        basename = os.path.basename(file)
                        rel_path_parts = os.path.relpath(filepath, target_path).split(os.sep)

                        # Check ignore lists
                        is_ignored_dir = any(part in dir_ignore for part in rel_path_parts[:-1])
                        is_ignored_file = any(fnmatch.fnmatch(basename, pattern) for pattern in file_ignore)

                        if is_ignored_dir or is_ignored_file:
                            # print(f"Ignoring: {filepath}") # Optional debug
                            continue
                        if ext in SUPPORTED_EXTENSIONS and not is_likely_binary(filepath):
                            files_to_process.append(filepath)
            except Exception as e:
                print(f"Error walking directory {target_path}: {e}")
                self._queue_ui_update("alert", {"level":"showerror", "title":"Directory Error", "message":f"Error scanning directory:\n{e}"})
                self._queue_ui_update("processing_done", {"total": 0}); return

        elif os.path.isfile(target_path):
            total_files_checked = 1
            if os.path.splitext(target_path)[1].lower() in SUPPORTED_EXTENSIONS and not is_likely_binary(target_path):
                files_to_process.append(target_path)
        else:
            self._queue_ui_update("alert", {"level":"showerror", "title":"Selection Error", "message":f"Invalid selection: {target_path}"})
            self._queue_ui_update("processing_done", {"total": 0}); return

        num_files = len(files_to_process)
        if not files_to_process:
            msg = f"Checked {total_files_checked} files. No supported, non-ignored files found to process."
            self._queue_ui_update("alert", {"level":"showinfo", "title":"No Files", "message":msg})
            self._queue_ui_update("processing_done", {"total": 0}); return

        self._queue_ui_update("progress_max", num_files)
        processed_count = 0
        # Use temporary dictionaries within thread to avoid direct mutation of shared state
        local_originals = {}
        local_processed = {}

        for i, filepath in enumerate(files_to_process):
            self._queue_ui_update("progress_update", {"increment": 0, "filename": os.path.basename(filepath)})
            original, processed = self._process_single_file(filepath, options)

            if processed is not None: # Processing didn't raise critical error
                # Store result if content actually changed
                if original != processed:
                    local_originals[filepath] = original
                    local_processed[filepath] = processed
                    # Queue update to add to UI listbox
                    self._queue_ui_update("add_listbox", {"filepath": filepath, "base_dir": base_dir})
                    processed_count += 1
                else:
                    # Optional: Log files that were checked but unchanged
                    # print(f"No changes needed for: {os.path.basename(filepath)}")
                    pass
            # Always increment progress bar step after trying a file
            self._queue_ui_update("progress_update", {"increment": 1})
            time.sleep(0.005) # Small delay to prevent tight loop, helps UI responsiveness

        # --- Post-processing: Update shared state safely ---
        # Only store original content for files that were actually modified
        self.original_content = local_originals # Replace main original cache
        self.processed_content.update(local_processed) # Add newly processed files

        self._queue_ui_update("processing_done", {"total": processed_count})

    def _process_single_file(self, filepath, options):
        """Reads, cleans, and formats (internally) a single file."""
        original_code = None
        try:
            # --- Read File with Encoding Detection ---
            encodings_to_try = ['utf-8', 'latin-1', 'cp1252']
            for enc in encodings_to_try:
                try:
                    with open(filepath, 'r', encoding=enc) as f:
                        original_code = f.read()
                    # print(f"Read {os.path.basename(filepath)} with {enc}") # Debug
                    break
                except UnicodeDecodeError:
                    continue
                except Exception as read_err:
                    print(f"Read error for {filepath} with {enc}: {read_err}")
                    break # Don't try other encodings if fundamental read error
            if original_code is None: # Fallback read
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        original_code = f.read()
                    print(f"Warning: Read {os.path.basename(filepath)} with UTF-8 ignoring errors.")
                except Exception as fallback_read_err:
                    print(f"CRITICAL Error reading file {filepath}: {fallback_read_err}")
                    self._queue_ui_update("alert", {"level":"showerror", "title":"Read Error", "message":f"Could not read file:\n{os.path.basename(filepath)}\n{fallback_read_err}"})
                    return None, None # Indicate failure

            # --- Apply Cleaning/Formatting Steps ---
            processed_code = original_code
            file_extension = os.path.splitext(filepath)[1].lower()

            if options["remove_comments"]:
                processed_code = remove_comments_by_type(processed_code, file_extension)

            # **Crucial:** Apply empty line removal AFTER comment removal
            if options["remove_empty_lines"]:
                processed_code = remove_extra_empty_lines_smart(processed_code)

            # --- Internal Basic Formatting ---
            # Only apply if relevant, potentially AFTER cleaning
            formatted_code, success = format_internal_basic(processed_code, file_extension)
            if success:
                processed_code = formatted_code # Use formatted version if successful

            # --- Apply EOL Conversion LAST ---
            target_eol = options.get("set_eol", "CRLF")
            final_code = normalize_eol(processed_code, target_eol)

            return original_code, final_code

        except Exception as e:
            print(f"ERROR processing file {os.path.basename(filepath)}: {e}\n{traceback.format_exc()}")
            self._queue_ui_update("alert", {"level":"showerror", "title":"Processing Error", "message":f"Error during processing:\n{os.path.basename(filepath)}\n{e}"})
            # Return original if read was successful, else None indicates total failure
            return original_code, None

        # --- File Saving ---
    def _save_files(self, filepaths_to_save):
        """Internal method to write processed content back to files."""
        saved_count = 0
        error_count = 0
        # target_eol = self.current_eol.get() # We still use this for normalize_eol
        # newline_char = '\r\n' if target_eol == "CRLF" else '\n' # No longer needed for open()

        self._queue_ui_update("status", {"data":f"Saving {len(filepaths_to_save)} files..."})

        for filepath in filepaths_to_save:
            # final_code ALREADY has correct line endings (\r\n or \n) from _process_single_file
            final_code = self.processed_content.get(filepath)

            if final_code is None:
                print(f"Warning: No processed content found for {filepath} during save.")
                error_count += 1
                continue

            try:
                dir_name = os.path.dirname(filepath)
                if dir_name:
                    os.makedirs(dir_name, exist_ok=True)

                # --- *** THE FIX IS HERE *** ---
                # Write the file using 'utf-8' encoding.
                # Set newline='' to disable universal newlines translation during writing.
                # This ensures the \r\n or \n characters already present in final_code
                # are written directly without modification.
                with open(filepath, 'w', encoding='utf-8', newline='') as f:
                    f.write(final_code)
                # --- *** END FIX *** ---

                saved_count += 1
            except Exception as e:
                error_count += 1
                print(f"ERROR saving file {filepath}: {e}")
                self._queue_ui_update("alert", {"level":"showerror", "title":"Save Error", "message":f"Failed to save:\n{os.path.basename(filepath)}\n{e}"})

        msg = f"Successfully saved {saved_count} files."
        if error_count > 0: msg += f" Failed to save {error_count} files."
        self._queue_ui_update("status", {"data": msg})
        
    # --- Preview Update & State Management ---

    def _reset_ui_state(self):
        """Clears previews, file list, caches, and resets button states."""
        self.file_listbox.delete(0, tk.END)
        self._update_preview_panes(None, None) # Clear panes
        # Disable after_text (already done in _apply_theme/_update_preview, but be sure)
        self.after_text.config(state=tk.DISABLED)
        self.processed_content.clear()
        self.original_content.clear() # Clear undo state on reset
        self.preview_label.config(text="Preview")
        self.progress_bar['value'] = 0
        self.status_label.config(text="Ready")
        self._update_button_states(force_disable=True)
        self.listbox_path_map.clear() # Clear the path mapping
        self.processing_base_dir = None

    def _update_button_states(self, force_disable=False):
         """ Enables/Disables Save and Undo buttons based on state """
         # Enable Save if there is processed content ready to be saved
         save_state = tk.NORMAL if self.processed_content and not force_disable else tk.DISABLED
         # Enable Undo only if original content exists (for files modified in the *last* run)
         undo_state = tk.NORMAL if self.original_content and not force_disable else tk.DISABLED
         self.save_button.config(state=save_state)
         self.undo_button.config(state=undo_state)
         try: # Update menu item states using their indices
             self.file_menu.entryconfig(self.save_menu_item_idx, state=save_state)
             self.edit_menu.entryconfig(self.undo_menu_item_idx, state=undo_state)
         except tk.TclError: pass # Ignore potential errors during shutdown/setup
         except AttributeError: pass # Ignore if menus/indices aren't setup yet

    def _get_selected_filepath_from_listbox(self):
        """Gets the full path of the file selected in the listbox."""
        selection_indices = self.file_listbox.curselection()
        if not selection_indices:
            return None
        try:
            selected_index = selection_indices[0]
            display_path = self.file_listbox.get(selected_index)
            # --- Look up the full path from the map ---
            full_path = self.listbox_path_map.get(display_path)
            if not full_path:
                print(f"Warning: Could not find full path for display path '{display_path}'")
            return full_path
        except tk.TclError: # Catch potential error if listbox is modified during access
            return None
        except KeyError: # Catch if display path somehow not in map
            print(f"Warning: Display path '{display_path}' not found in mapping.")
            return None
        
    def _get_content_from_cache(self, filepath=None):
        """ Gets the original and processed content for the preview """
        if filepath is None: filepath = self._get_selected_filepath_from_listbox()
        if not filepath: return None, None
        # Return copies or handle potential modification elsewhere? For now, direct refs.
        return self.original_content.get(filepath), self.processed_content.get(filepath)

    def _update_preview_panes(self, original_code, processed_code):
         """ Updates the text widgets and highlights differences """
         # Ensure widgets are temporarily enabled for update
         self.before_text.config(state=tk.NORMAL)
         self.after_text.config(state=tk.NORMAL) # Enable AFTER briefly to allow insert

         # Clear existing content and tags
         self.before_text.delete('1.0', tk.END)
         self.after_text.delete('1.0', tk.END)
         self.before_text.tag_remove("difference", "1.0", tk.END)
         self.after_text.tag_remove("difference", "1.0", tk.END)

         # Insert new content
         if original_code is not None: self.before_text.insert('1.0', original_code)
         if processed_code is not None: self.after_text.insert('1.0', processed_code)

         # Calculate and highlight differences
         if original_code is not None and processed_code is not None:
             # Use splitlines(keepends=True) if exact EOL diff is important,
             # otherwise splitlines() is better for visual line diff.
             before_lines = original_code.splitlines()
             after_lines = processed_code.splitlines()
             diff = difflib.ndiff(before_lines, after_lines)
             b_ln, a_ln = 1, 1 # Line numbers for text widgets start at 1
             for line in diff:
                 code = line[0] # '+', '-', ' '
                 if code == '-':
                     start, end = f"{b_ln}.0", f"{b_ln}.end"
                     self.before_text.tag_add("difference", start, end)
                     b_ln += 1
                 elif code == '+':
                     start, end = f"{a_ln}.0", f"{a_ln}.end"
                     self.after_text.tag_add("difference", start, end)
                     a_ln += 1
                 elif code == ' ':
                     b_ln += 1; a_ln += 1
                 # Ignore '?' lines

         # Ensure correct states are set finally
         self.before_text.config(state=tk.DISABLED)
         self.after_text.config(state=tk.DISABLED) # Keep AFTER pane disabled

         # Scroll both panes to top
         try:
             self.before_text.yview_moveto(0); self.after_text.yview_moveto(0)
         except tk.TclError: pass # Ignore scroll errors if widget not fully ready


    # --- Queue Processing ---

    def check_queue(self):
        """ Checks the UI update queue and processes messages """
        try:
            while True: # Process all messages currently in queue
                message = self.ui_update_queue.get_nowait()
                msg_type = message.get("type")
                data = message.get("data", {})

                # --- Handle different message types ---
                if msg_type == "status":
                     # Update status bar only if not actively processing
                     if not self.is_processing: self.status_label.config(text=data)
                elif msg_type == "progress_max":
                    self.progress_bar.config(maximum=data, value=0)
                elif msg_type == "progress_update":
                    # Update progress bar and potentially the status label with filename
                    self.progress_bar.step(data.get("increment", 1)) # Assume step=1 if not given
                    filename = data.get("filename")
                    if filename and self.is_processing:
                         self.status_label.config(text=f"Processing: {filename}")
                elif msg_type == "add_listbox":
                    # Add processed file path to the listbox
                    filepath = data.get("filepath")
                    base_dir = data.get("base_dir") # Get base dir from message
                    if filepath:
                        # Calculate display path
                        if base_dir and os.path.isdir(base_dir): # Check if base_dir is valid
                            # Use normpath for cleaner relative paths (e.g., remove redundant slashes)
                            try:
                                display_path = os.path.normpath(os.path.relpath(filepath, base_dir))
                            except ValueError: # Handle case where filepath might be on different drive than base_dir on Windows
                                display_path = os.path.basename(filepath) # Fallback to filename
                        else: # If no valid base_dir (likely single file processed), just use filename
                            display_path = os.path.basename(filepath)

                        # Add to listbox
                        self.file_listbox.insert(tk.END, display_path)
                        # --- Store mapping from display path to full path ---
                        self.listbox_path_map[display_path] = filepath
                elif msg_type == "processing_start":
                    # Update UI to reflect start of processing
                    self.is_processing = True
                    self.process_button.config(state=tk.DISABLED)
                    self.update_loading_animation() # Start '...' animation
                elif msg_type == "processing_done":
                    # Update UI to reflect end of processing
                    self.is_processing = False
                    self.loading_animation_label.config(text="") # Clear animation
                    total = data.get("total", 0)
                    # Update status bar message
                    self.status_label.config(text=f"Processing Complete. {total} file(s) modified.")
                    # Ensure progress bar is full
                    max_val = self.progress_bar.cget('maximum')
                    self.progress_bar['value'] = max_val if max_val > 0 else 0
                    # Re-enable process button
                    self.process_button.config(state=tk.NORMAL)
                    # Auto-select first item if list populated
                    if total > 0 and self.file_listbox.size() > 0:
                         if not self.file_listbox.curselection(): # If nothing is selected
                             self.file_listbox.selection_set(0) # Select the first item
                         self._on_file_select() # Trigger preview update for selection
                    # Refresh button states based on processing results
                    self._update_button_states()
                elif msg_type == "alert":
                    # Show a messagebox (error, warning, info)
                    level = data.get("level", "showinfo")
                    title = data.get("title", "Information")
                    message = data.get("message", "An event occurred.")
                    getattr(messagebox, level, messagebox.showinfo)(title, message)

        except queue.Empty:
            pass # No messages currently.
        finally:
            # Reschedule the check
            self.root.after(100, self.check_queue)

    def _queue_ui_update(self, msg_type, data=None):
         """ Safely put a message onto the UI update queue """
         self.ui_update_queue.put({"type": msg_type, "data": data})

    # --- Loading Animation Methods ---
    loading_animation_chars = ["", ".", "..", "...", " ..", " ."] # Cycle dots
    loading_animation_index = 0
    is_processing = False # Flag to control animation loop

    def update_loading_animation(self):
        """Updates the simple '...' animation label."""
        if self.is_processing:
            self.loading_animation_label.config(text=self.loading_animation_chars[self.loading_animation_index])
            self.loading_animation_index = (self.loading_animation_index + 1) % len(self.loading_animation_chars)
            self.root.after(350, self.update_loading_animation) # Adjust speed
        else:
            self.loading_animation_label.config(text="") # Clear when done


# --- Main Execution ---
if __name__ == "__main__":
    root = tk.Tk()
    app = CodeCleanerApp(root)
    root.mainloop()
