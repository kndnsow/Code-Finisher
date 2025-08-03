#!/usr/bin/env python3

import sys
import os
import re
import threading
import queue
import time
import difflib
import fnmatch
import json
import xml.dom.minidom

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QFileDialog, QMessageBox, QTextEdit,
    QPushButton, QCheckBox, QListWidget, QLabel, QProgressBar,
    QVBoxLayout, QHBoxLayout, QWidget, QMenu, QSplitter, QFrame
)
from PyQt6.QtGui import QIcon, QFont, QTextCharFormat, QColor
from PyQt6.QtCore import Qt, QTimer

if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- Configuration Constants ---
SUPPORTED_EXTENSIONS = [
    ".py", ".c", ".h", ".html", ".css", ".scss", ".less", ".js", ".jsx", ".ts", ".tsx",
    ".php", ".cs", ".cpp", ".java", ".json", ".xml", ".yaml", ".yml", ".md"
]

DEFAULT_IGNORE_PATTERNS = [
    "*.log", "*.tmp", "*.bak", "*.swp", "*.pyc",
    "__pycache__/", "node_modules/", "vendor/",
    ".git/", ".svn/", ".hg/",
    "dist/", "build/", "target/",
    "*.min.js", "*.min.css"
]

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

def normalize_eol(code, eol_sequence):
    """Converts all line endings to the specified sequence ('CRLF' or 'LF')."""
    if not isinstance(code, str): return code # Safety check
    # Normalize all to LF first
    normalized_code = code.replace('\r\n', '\n').replace('\r', '\n')
    # Convert to target EOL
    if eol_sequence == "CRLF":
        return normalized_code.replace('\n', '\r\n')
    return normalized_code

def remove_comments_by_type(code, file_extension):
    """Removes comments based on typical language syntax using regex.
    Note: Regex-based removal has limitations and may fail on complex edge cases
    (e.g., comments within string literals that look like comments).
    """
    if not isinstance(code, str): return code # Safety check
    original_code = code

    try:
        if file_extension == ".py":
            # Remove full-line comments but keep the newline
            code = re.sub(r'^[ \t]*#.*', '', code, flags=re.MULTILINE)
            # Remove inline comments leaving the preceding code and newline untouched
            code = re.sub(r'(?m)([^\'"])\s+#.*', r'\1', code)

        elif file_extension in [".c", ".cpp", ".h", ".hpp", ".java", ".m", ".js", ".jsx", ".ts", ".tsx", ".cs", ".css", ".scss", ".less"]:
            # Remove /* … */ block comments without touching newlines
            def _strip_block(match):
                text = match.group(0)
                # Count newlines in the block and preserve them
                return '\n' * text.count('\n')
            code = re.sub(r'/\*[\s\S]*?\*/', _strip_block, code)
            # Remove //… comments but keep the newline
            code = re.sub(r'(?<!:)//.*', '', code)

        elif file_extension in [".html", ".xml"]:
            # Remove HTML/XML <!-- --> comments but preserve line breaks
            def _strip_html_block(match):
                text = match.group(0)
                return '\n' * text.count('\n')
            code = re.sub(r'<!--[\s\S]*?-->', _strip_html_block, code)

        elif file_extension == ".php":
            # Block comments (/* … */)
            def _strip_block(match):
                text = match.group(0)
                return '\n' * text.count('\n')
            code = re.sub(r'/\*[\s\S]*?\*/', _strip_block, code)
            # Line comments: // and #
            code = re.sub(r'(?<!:)//.*', '', code)
            code = re.sub(r'#.*', '', code)

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

class CodeCleanerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Code Cleaner")
        
        icon_path = os.path.join(BASE_DIR, "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # --- State Variables ---
        self.selected_paths = [] # Paths selected by user (file or dir)
        self.original_content = {} # Cache for original file content {filepath: content}
        self.processed_content = {} # Cache for processed content {filepath: content}
        self.current_eol = "CRLF" # User's choice for line ending
        self.remove_comments_var = True
        self.remove_empty_lines_var = True
        self.current_processing_file = "" # For status bar display

        # Use default ignore patterns, loaded into the UI text widget
        self.ignore_patterns = list(DEFAULT_IGNORE_PATTERNS)

        # Queue for communication between processing thread and UI thread
        self.ui_update_queue = queue.Queue()

        self.listbox_path_map = {}
        self.processing_base_dir = None
        self.is_processing = False

        self._build_menu()
        self._build_ui()
        self._bind_events()
        self._start_queue_timer()
        
        # Set window size and maximize AFTER UI is built
        self._maximize_window()

    def _maximize_window(self):
        """Properly maximize the window"""
        # First set a reasonable default size
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(int(screen.width() * 0.9), int(screen.height() * 0.9))
        
        # Move to center
        self.move(int(screen.width() * 0.05), int(screen.height() * 0.05))
        
        # Now maximize
        self.showMaximized()

    def _build_menu(self):
        bar = self.menuBar()
        
        # File Menu
        file_menu = bar.addMenu("File")
        file_menu.addAction("Select File...", self.select_file)
        file_menu.addAction("Select Directory...", self.select_directory)
        file_menu.addSeparator()
        self.save_action = file_menu.addAction("Save All Changes", self.save_all_changes_action)
        self.save_action.setEnabled(False)
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.close)

        # Edit Menu
        edit_menu = bar.addMenu("Edit")
        self.undo_action = edit_menu.addAction("Undo All (Session)", self.undo_all_changes_action)
        self.undo_action.setEnabled(False)

        # View Menu (Simplified - only EOL)
        view_menu = bar.addMenu("View")
        eol_menu = QMenu("EOL Sequence", self)
        view_menu.addMenu(eol_menu)
        eol_menu.addAction("CRLF (Windows)", lambda: self._set_eol("CRLF"))
        eol_menu.addAction("LF (Unix/Mac)", lambda: self._set_eol("LF"))

    def _build_ui(self):
        main = QWidget()
        self.setCentralWidget(main)

        # Main horizontal splitter - resizable panels
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(5, 5, 5, 5)
        
        # Control panel (left side) - resizable
        self.control_frame = QWidget()
        self.control_frame.setMinimumWidth(250)
        
        # Preview frame (right side) - resizable  
        self.preview_frame = QWidget()
        
        # Add to main splitter
        self.main_splitter.addWidget(self.control_frame)
        self.main_splitter.addWidget(self.preview_frame)
        
        # Set initial sizes: 25% left, 75% right
        self.main_splitter.setSizes([300, 900])
        self.main_splitter.setStretchFactor(0, 0)  # Control panel doesn't stretch much
        self.main_splitter.setStretchFactor(1, 1)  # Preview takes most expansion
        
        # Status bar (bottom) - fixed height
        self.status_frame = QWidget()
        self.status_frame.setMaximumHeight(30)
        
        # Add to main layout
        main_layout.addWidget(self.main_splitter, 1)  # Splitter takes most space
        main_layout.addWidget(self.status_frame)      # Status at bottom

        self._setup_control_panel()
        self._setup_preview_panel()
        self._setup_status_bar()

    def _setup_control_panel(self):
        """Creates widgets for the left control panel."""
        layout = QVBoxLayout(self.control_frame)
        layout.setContentsMargins(10, 10, 10, 10)

        # Buttons
        self.btn_select_file = QPushButton("Select File...")
        self.btn_select_directory = QPushButton("Select Directory...")
        layout.addWidget(self.btn_select_file)
        layout.addWidget(self.btn_select_directory)

        # Options
        layout.addSpacing(10)
        self.chk_remove_comments = QCheckBox("Remove Comments")
        self.chk_remove_comments.setChecked(True)
        self.chk_remove_empty_lines = QCheckBox("Remove Extra Empty Lines")
        self.chk_remove_empty_lines.setChecked(True)
        layout.addWidget(self.chk_remove_comments)
        layout.addWidget(self.chk_remove_empty_lines)

        # Action Buttons
        layout.addSpacing(15)
        self.btn_process = QPushButton("Process Selected")
        self.btn_save = QPushButton("Save All Changes")
        self.btn_save.setEnabled(False)
        self.btn_undo = QPushButton("Undo All (Session)")
        self.btn_undo.setEnabled(False)
        
        layout.addWidget(self.btn_process)
        layout.addWidget(self.btn_save)
        layout.addWidget(self.btn_undo)

        # Processed Files List - EXPANDABLE
        layout.addSpacing(15)
        lbl_files = QLabel("Processed Files:")
        layout.addWidget(lbl_files)
        self.file_listbox = QListWidget()
        # Remove height restriction to make it expandable
        self.file_listbox.setMinimumHeight(100)  # Minimum height only
        layout.addWidget(self.file_listbox, 1)  # Give it stretch factor so it expands

        # Ignore List - Fixed size
        layout.addSpacing(10)
        lbl_ignore = QLabel("Ignore Patterns (Glob):")
        layout.addWidget(lbl_ignore)
        self.ignore_list_text = QTextEdit("\n".join(self.ignore_patterns))
        self.ignore_list_text.setMaximumHeight(100)
        layout.addWidget(self.ignore_list_text)

    def _setup_preview_panel(self):
        """Creates widgets for the preview area with resizable Before/After panels."""
        layout = QVBoxLayout(self.preview_frame)
        layout.setContentsMargins(5, 10, 10, 0)

        self.preview_label = QLabel("Preview: Select a file from the list")
        layout.addWidget(self.preview_label)

        # Before/After title labels
        titles_layout = QHBoxLayout()
        self.before_title_label = QLabel("Before")
        self.after_title_label = QLabel("After")
        self.before_title_label.setStyleSheet("font-weight: bold; padding: 5px;")
        self.after_title_label.setStyleSheet("font-weight: bold; padding: 5px;")
        titles_layout.addWidget(self.before_title_label)
        titles_layout.addWidget(self.after_title_label)
        layout.addLayout(titles_layout)

        # Vertical splitter for Before/After text areas - RESIZABLE
        self.text_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Before text
        self.before_text = QTextEdit()
        self.before_text.setReadOnly(True)
        self.before_text.setFont(QFont("Consolas", 10))
        
        # After text
        self.after_text = QTextEdit()
        self.after_text.setReadOnly(True)
        self.after_text.setFont(QFont("Consolas", 10))
        
        # Add to splitter
        self.text_splitter.addWidget(self.before_text)
        self.text_splitter.addWidget(self.after_text)
        
        # Set equal sizes for Before/After
        self.text_splitter.setSizes([400, 400])
        self.text_splitter.setStretchFactor(0, 1)
        self.text_splitter.setStretchFactor(1, 1)
        
        # Add splitter to main layout - takes all remaining space
        layout.addWidget(self.text_splitter, 1)

    def _setup_status_bar(self):
        layout = QHBoxLayout(self.status_frame)
        layout.setContentsMargins(10, 5, 10, 5)

        self.status_label = QLabel("Ready")
        self.loading_animation_label = QLabel("")
        self.progress_bar = QProgressBar()
        # Remove fixed width:
        # self.progress_bar.setMaximumWidth(200)
        layout.addWidget(self.status_label, 1)           # status takes weight 1
        layout.addWidget(self.loading_animation_label, 0)
        layout.addWidget(self.progress_bar, 2)            # progress takes weight 1 (50% of total)


    def _bind_events(self):
        """Binds UI events to their handler methods."""
        self.btn_select_file.clicked.connect(self.select_file)
        self.btn_select_directory.clicked.connect(self.select_directory)
        self.btn_process.clicked.connect(self.start_processing_action)
        self.btn_save.clicked.connect(self.save_all_changes_action)
        self.btn_undo.clicked.connect(self.undo_all_changes_action)
        self.file_listbox.currentTextChanged.connect(self.on_file_select)
        self.ignore_list_text.textChanged.connect(self.update_ignore_patterns)

    def _start_queue_timer(self):
        timer = QTimer(self)
        timer.timeout.connect(self.check_queue)
        timer.start(100)

    def _set_eol(self, val):
        self.current_eol = val

    def select_file(self):
        """Handles the 'Select File' action."""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Select Code File",
            filter="Code Files (" + " ".join(f"*{ext}" for ext in SUPPORTED_EXTENSIONS) + ");;All Files (*.*)"
        )
        if filepath:
            self.selected_paths = [filepath]
            self.status_label.setText(f"Selected: {os.path.basename(filepath)}")
            self.reset_ui_state()

    def select_directory(self):
        """Handles the 'Select Directory' action."""
        dirpath = QFileDialog.getExistingDirectory(self, "Select Project Directory")
        if dirpath:
            self.selected_paths = [dirpath]
            self.status_label.setText(f"Selected Dir: {os.path.basename(dirpath)}")
            self.reset_ui_state()

    def update_ignore_patterns(self):
        """Reads ignore patterns from text widget and updates internal list."""
        self.ignore_patterns = [
            p.strip() for p in self.ignore_list_text.toPlainText().splitlines() if p.strip()
        ]

    def start_processing_action(self):
        """Starts the file processing thread when 'Process Selected' is clicked."""
        if not self.selected_paths:
            QMessageBox.warning(self, "No Selection", "Please select a file or directory first.")
            return

        self.reset_ui_state()

        # Gather options
        options = {
            "remove_comments": self.chk_remove_comments.isChecked(),
            "remove_empty_lines": self.chk_remove_empty_lines.isChecked(),
            "set_eol": self.current_eol,
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
            target=self.processing_thread_worker,
            args=(target, options, self.processing_base_dir),
            daemon=True
        )
        thread.start()

    def processing_thread_worker(self, target_path, options, base_dir):
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
                            continue

                        if ext in SUPPORTED_EXTENSIONS and not is_likely_binary(filepath):
                            files_to_process.append(filepath)

            except Exception as e:
                print(f"Error walking directory {target_path}: {e}")
                self.queue_ui_update("alert", {"level":"showerror", "title":"Directory Error", "message":f"Error scanning directory:\n{e}"})
                self.queue_ui_update("processing_done", {"total": 0})
                return

        elif os.path.isfile(target_path):
            total_files_checked = 1
            if os.path.splitext(target_path)[1].lower() in SUPPORTED_EXTENSIONS and not is_likely_binary(target_path):
                files_to_process.append(target_path)
            else:
                self.queue_ui_update("alert", {"level":"showerror", "title":"Selection Error", "message":f"Invalid selection: {target_path}"})
                self.queue_ui_update("processing_done", {"total": 0})
                return

        num_files = len(files_to_process)
        if not files_to_process:
            msg = f"Checked {total_files_checked} files. No supported, non-ignored files found to process."
            self.queue_ui_update("alert", {"level":"showinfo", "title":"No Files", "message":msg})
            self.queue_ui_update("processing_done", {"total": 0})
            return

        self.queue_ui_update("progress_max", num_files)
        processed_count = 0

        # Use temporary dictionaries within thread to avoid direct mutation of shared state
        local_originals = {}
        local_processed = {}

        for i, filepath in enumerate(files_to_process):
            self.queue_ui_update("progress_update", {"increment": 0, "filename": os.path.basename(filepath)})

            original, processed = self.process_single_file(filepath, options)

            if processed is not None: # Processing didn't raise critical error
                # Store result if content actually changed
                if original != processed:
                    local_originals[filepath] = original
                    local_processed[filepath] = processed

                    # Queue update to add to UI listbox
                    self.queue_ui_update("add_listbox", {"filepath": filepath, "base_dir": base_dir})
                    processed_count += 1

            # Always increment progress bar step after trying a file
            self.queue_ui_update("progress_update", {"increment": 1})
            time.sleep(0.005) # Small delay to prevent tight loop, helps UI responsiveness

        # --- Post-processing: Update shared state safely ---
        # Only store original content for files that were actually modified
        self.original_content = local_originals # Replace main original cache
        self.processed_content.update(local_processed) # Add newly processed files

        self.queue_ui_update("processing_done", {"total": processed_count})

    def process_single_file(self, filepath, options):
        """Reads, cleans, and formats (internally) a single file."""
        original_code = None

        try:
            # --- Read File with Encoding Detection ---
            encodings_to_try = ['utf-8', 'latin-1', 'cp1252']
            for enc in encodings_to_try:
                try:
                    with open(filepath, 'r', encoding=enc) as f:
                        original_code = f.read()
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
                    self.queue_ui_update("alert", {"level":"showerror", "title":"Read Error", "message":f"Could not read file:\n{os.path.basename(filepath)}\n{fallback_read_err}"})
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
            print(f"ERROR processing file {os.path.basename(filepath)}: {e}")
            self.queue_ui_update("alert", {"level":"showerror", "title":"Processing Error", "message":f"Error during processing:\n{os.path.basename(filepath)}\n{e}"})
            # Return original if read was successful, else None indicates total failure
            return original_code, None

    def save_all_changes_action(self):
        """Handles the 'Save All Changes' action, prompting the user first."""
        files_to_save = list(self.processed_content.keys())
        if not files_to_save:
            QMessageBox.information(self, "No Changes", "No processed files available to save.")
            return

        reply = QMessageBox.question(
            self, "Confirm Save",
            f"This will OVERWRITE {len(files_to_save)} original file(s) with the cleaned version.\n\n"
            "MAKE SURE YOU HAVE BACKUPS if necessary!\n\nAre you absolutely sure?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return # User cancelled

        # Perform save (using save_files internal method)
        self.save_files(files_to_save)

    def save_files(self, filepaths_to_save):
        """Internal method to write processed content back to files."""
        saved_count = 0
        error_count = 0

        self.queue_ui_update("status", {"data":f"Saving {len(filepaths_to_save)} files..."})

        for filepath in filepaths_to_save:
            # final_code ALREADY has correct line endings (\r\n or \n) from process_single_file
            final_code = self.processed_content.get(filepath)
            if final_code is None:
                print(f"Warning: No processed content found for {filepath} during save.")
                error_count += 1
                continue

            try:
                dir_name = os.path.dirname(filepath)
                if dir_name:
                    os.makedirs(dir_name, exist_ok=True)

                # Write the file using 'utf-8' encoding.
                # Set newline='' to disable universal newlines translation during writing.
                # This ensures the \r\n or \n characters already present in final_code
                # are written directly without modification.
                with open(filepath, 'w', encoding='utf-8', newline='') as f:
                    f.write(final_code)

                saved_count += 1
            except Exception as e:
                error_count += 1
                print(f"ERROR saving file {filepath}: {e}")
                self.queue_ui_update("alert", {"level":"showerror", "title":"Save Error", "message":f"Failed to save:\n{os.path.basename(filepath)}\n{e}"})

        msg = f"Successfully saved {saved_count} files."
        if error_count > 0: 
            msg += f" Failed to save {error_count} files."

        self.queue_ui_update("status", {"data": msg})

    def undo_all_changes_action(self):
        """Handles the 'Undo All' action, reverting in-memory changes."""
        if not self.original_content:
            QMessageBox.information(self, "Nothing to Undo", "No original state saved from the last processing run.")
            return

        reply = QMessageBox.question(
            self, "Confirm Session Undo",
            "Revert all changes in the preview panes back to their state BEFORE the last 'Process Selected' was run?\n\n(This does NOT affect files already saved to disk).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return # User cancelled

        # Restore processed cache from original cache
        self.processed_content.clear()
        self.processed_content.update(self.original_content)

        # Clear original cache - Undo is now 'spent' for this processing run
        self.original_content.clear()

        # Refresh the preview if a file is selected
        if self.get_selected_filepath_from_listbox():
            self.on_file_select() # This will re-run diff (now showing no difference)
        else:
            self.update_preview_panes(None, None) # Clear preview if nothing selected

        self.status_label.setText("Changes reverted in preview (Session Undo).")
        self.update_button_states() # Update buttons (Undo should now be disabled)

    def on_file_select(self, event=None):
        """Updates preview panes when a file is selected in the listbox."""
        filepath = self.get_selected_filepath_from_listbox()

        if not filepath:
            self.preview_label.setText("Preview")
            self.update_preview_panes(None, None) # Clear preview
            return

        # Retrieve content from caches
        original_code, processed_code = self.get_content_from_cache(filepath)

        # Update label and panes
        self.preview_label.setText(f"Preview: {os.path.basename(filepath)}")
        self.update_preview_panes(original_code, processed_code)

    def reset_ui_state(self):
        """Clears previews, file list, caches, and resets button states."""
        self.file_listbox.clear()
        self.update_preview_panes(None, None) # Clear panes

        self.processed_content.clear()
        self.original_content.clear() # Clear undo state on reset

        self.preview_label.setText("Preview")
        self.progress_bar.setValue(0)
        self.status_label.setText("Ready")
        self.update_button_states(force_disable=True)
        self.listbox_path_map.clear() # Clear the path mapping
        self.processing_base_dir = None

    def update_button_states(self, force_disable=False):
        """ Enables/Disables Save and Undo buttons based on state """
        # Enable Save if there is processed content ready to be saved
        save_state = bool(self.processed_content) and not force_disable
        # Enable Undo only if original content exists (for files modified in the *last* run)
        undo_state = bool(self.original_content) and not force_disable

        self.btn_save.setEnabled(save_state)
        self.btn_undo.setEnabled(undo_state)
        self.save_action.setEnabled(save_state)
        self.undo_action.setEnabled(undo_state)

    def get_selected_filepath_from_listbox(self):
        """Gets the full path of the file selected in the listbox."""
        current_item = self.file_listbox.currentItem()
        if not current_item:
            return None

        display_path = current_item.text()
        # Look up the full path from the map
        full_path = self.listbox_path_map.get(display_path)
        if not full_path:
            print(f"Warning: Could not find full path for display path '{display_path}'")
        return full_path

    def get_content_from_cache(self, filepath=None):
        """ Gets the original and processed content for the preview """
        if filepath is None: 
            filepath = self.get_selected_filepath_from_listbox()
        if not filepath: 
            return None, None

        return self.original_content.get(filepath), self.processed_content.get(filepath)

    def update_preview_panes(self, original_code, processed_code):
        """ Updates the text widgets and highlights differences """
        # Clear existing content
        self.before_text.clear()
        self.after_text.clear()

        # Insert new content
        if original_code is not None: 
            self.before_text.setPlainText(original_code)
        if processed_code is not None: 
            self.after_text.setPlainText(processed_code)

        # Calculate and highlight differences
        if original_code is not None and processed_code is not None:
            self.highlight_differences(original_code, processed_code)

    def highlight_differences(self, before_content, after_content):
        """Highlights differences between before and after content."""
        before_lines = before_content.splitlines()
        after_lines = after_content.splitlines()
        
        diff = list(difflib.ndiff(before_lines, after_lines))
        
        # Create text formats for highlighting
        remove_format = QTextCharFormat()
        remove_format.setBackground(QColor("#6b2020"))  # Red background
        
        add_format = QTextCharFormat()
        add_format.setBackground(QColor("#206b20"))     # Green background
        
        # Apply highlighting to before text
        before_cursor = self.before_text.textCursor()
        before_cursor.movePosition(before_cursor.MoveOperation.Start)
        
        # Apply highlighting to after text
        after_cursor = self.after_text.textCursor()
        after_cursor.movePosition(after_cursor.MoveOperation.Start)
        
        b_line, a_line = 0, 0
        
        for line in diff:
            code = line[0]
            if code == '-':  # Line removed
                # Highlight this line in before text
                before_cursor.movePosition(before_cursor.MoveOperation.StartOfLine)
                before_cursor.movePosition(before_cursor.MoveOperation.EndOfLine, before_cursor.MoveMode.KeepAnchor)
                before_cursor.mergeCharFormat(remove_format)
                before_cursor.movePosition(before_cursor.MoveOperation.NextBlock)
                b_line += 1
            elif code == '+':  # Line added
                # Highlight this line in after text
                after_cursor.movePosition(after_cursor.MoveOperation.StartOfLine)
                after_cursor.movePosition(after_cursor.MoveOperation.EndOfLine, after_cursor.MoveMode.KeepAnchor)
                after_cursor.mergeCharFormat(add_format)
                after_cursor.movePosition(after_cursor.MoveOperation.NextBlock)
                a_line += 1
            elif code == ' ':  # Line unchanged
                before_cursor.movePosition(before_cursor.MoveOperation.NextBlock)
                after_cursor.movePosition(after_cursor.MoveOperation.NextBlock)
                b_line += 1
                a_line += 1

    def check_queue(self):
        """ Checks the UI update queue and processes messages """
        try:
            while True: # Process all messages currently in queue
                message = self.ui_update_queue.get_nowait()
                msg_type = message.get("type")
                data = message.get("data", {})

                # --- Handle different message types ---
                if msg_type == "status":
                    # data may be a dict {"data": msg} or a raw string
                    text = data["data"] if isinstance(data, dict) else data
                    self.status_label.setText(text)

                elif msg_type == "progress_max":
                    self.progress_bar.setMaximum(data)
                    self.progress_bar.setValue(0)

                elif msg_type == "progress_update":
                    # Update progress bar and potentially the status label with filename
                    increment = data.get("increment", 1)
                    self.progress_bar.setValue(self.progress_bar.value() + increment)
                    
                    filename = data.get("filename")
                    if filename and self.is_processing:
                        self.status_label.setText(f"Processing: {filename}")

                elif msg_type == "add_listbox":
                    # Add processed file path to the listbox
                    filepath = data.get("filepath")
                    base_dir = data.get("base_dir") # Get base dir from message

                    if filepath:
                        # Calculate display path
                        if base_dir and os.path.isdir(base_dir): # Check if base_dir is valid
                            try:
                                display_path = os.path.normpath(os.path.relpath(filepath, base_dir))
                            except ValueError: # Handle case where filepath might be on different drive than base_dir on Windows
                                display_path = os.path.basename(filepath) # Fallback to filename
                        else: # If no valid base_dir (likely single file processed), just use filename
                            display_path = os.path.basename(filepath)

                        # Add to listbox
                        self.file_listbox.addItem(display_path)
                        # Store mapping from display path to full path
                        self.listbox_path_map[display_path] = filepath

                elif msg_type == "processing_start":
                    # Update UI to reflect start of processing
                    self.is_processing = True
                    self.btn_process.setEnabled(False)
                    self.update_loading_animation() # Start '...' animation

                elif msg_type == "processing_done":
                    # Update UI to reflect end of processing
                    self.is_processing = False
                    self.loading_animation_label.setText("") # Clear animation

                    total = data.get("total", 0)
                    # Update status bar message
                    self.status_label.setText(f"Processing Complete. {total} file(s) modified.")

                    # Ensure progress bar is full
                    max_val = self.progress_bar.maximum()
                    self.progress_bar.setValue(max_val if max_val > 0 else 0)

                    # Re-enable process button
                    self.btn_process.setEnabled(True)

                    # Auto-select first item if list populated
                    if total > 0 and self.file_listbox.count() > 0:
                        if not self.file_listbox.currentItem(): # If nothing is selected
                            self.file_listbox.setCurrentRow(0) # Select the first item
                            self.on_file_select() # Trigger preview update for selection

                    # Refresh button states based on processing results
                    self.update_button_states()

                elif msg_type == "alert":
                    # Show a messagebox (error, warning, info)
                    level = data.get("level", "showinfo")
                    title = data.get("title", "Information")
                    message = data.get("message", "An event occurred.")
                    
                    if level == "showerror":
                        QMessageBox.critical(self, title, message)
                    elif level == "showwarning":
                        QMessageBox.warning(self, title, message)
                    else:
                        QMessageBox.information(self, title, message)

        except queue.Empty:
            pass # No messages currently.

    def queue_ui_update(self, msg_type, data=None):
        """ Safely put a message onto the UI update queue """
        self.ui_update_queue.put({"type": msg_type, "data": data})

    # --- Loading Animation Methods ---
    loading_animation_chars = ["", ".", "..", "...", " ..", " ."] # Cycle dots
    loading_animation_index = 0

    def update_loading_animation(self):
        """Updates the simple '...' animation label."""
        if self.is_processing:
            self.loading_animation_label.setText(self.loading_animation_chars[self.loading_animation_index])
            self.loading_animation_index = (self.loading_animation_index + 1) % len(self.loading_animation_chars)
            QTimer.singleShot(350, self.update_loading_animation) # Adjust speed
        else:
            self.loading_animation_label.setText("") # Clear when done

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = CodeCleanerApp()
    window.show()
    
    # To build a Windows executable with custom icon:
    # 1. Install PyInstaller: pip install pyinstaller
    # 2. Place your icon file (icon.ico) in the same folder as this script  
    # 3. Run: pyinstaller --onefile --windowed --icon=icon.ico Ultimate_Code_Finisher.py
    # This generates "Ultimate_Code_Finisher.exe" (with your icon) in the "dist" folder
    
    sys.exit(app.exec())