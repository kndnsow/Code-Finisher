# Code Cleaner (Ultimate Code Finisher)

A cross-platform desktop application for cleaning and formatting code files.  
Built in Python with a modern PyQt6 GUI, it removes comments and extra blank lines, normalizes line endings, and pretty-prints JSON/XML. Ideal for streamlining code cleanup across multiple languages.

![Application Screenshot](https://github.com/kndnsow/Code-Finisher/raw/main/Screenshots/Screenshot_0.png)

- **File & Directory Selection**  
  Process individual files or entire project directories (recursively).  
- **Language Support**  
  Handles comment styles for Python, JavaScript, Java, C/C++, C#, PHP, HTML, CSS, XML, and more.  
- **Comment Removal**  
  Strip single-line and multi-line comments via robust regex rules.  
- **Empty Line Consolidation**  
  Collapse multiple blank lines into a single blank line.  
- **EOL Normalization**  
  Convert line endings to CRLF (Windows) or LF (Unix/macOS).  
- **Basic Pretty-Printing**  
  Internal JSON and XML formatting with indent/cleanup.  
- **Ignore Patterns**  
  Glob-style patterns (e.g., `.git/`, `node_modules/`, `*.log`) to exclude files/directories.  
- **Dark Theme UI**  
  Consistent dark mode for comfortable code viewing.  
- **Side-by-Side Preview**  
  “Before” and “After” panes with inline diff highlighting (red for removals, green for additions).  
- **Undo Session**  
  Revert in-memory changes from the last processing run before saving.  
- **Save Changes**  
  Overwrite original files only after confirmation.  
- **Responsive UI**  
  Background processing thread keeps the GUI responsive, and panels are fully resizable.  
- **Cross-Platform Executable**  
  Build a standalone `.exe` with PyInstaller.

## Screenshot

![Code Cleaner Preview](https://github.com/kndnsow/Code-Finisher/raw/main/Screenshots/Screenshot_1.png)

### Prerequisites

- Python 3.7+
- pip

### Install Dependencies

Create a `requirements.txt` with:

```
PyQt6
```

Then install:

```bash
pip install -r requirements.txt
```

### Run from Source

```bash
python Ultimate_Code_Finisher.py
```

### Build Standalone Executable

1. Install PyInstaller:
   ```bash
   pip install pyinstaller
   ```
2. Place `icon.ico` alongside the script.
3. Run:
   ```bash
   pyinstaller --onefile --add-data "icon.ico;." --windowed --icon=icon.ico Ultimate_Code_Finisher.py
   ```
4. The executable appears in `dist/Ultimate_Code_Finisher.exe`.

## How to Use

1. **Select Source:**  
   Click **Select File...** or **Select Directory...**  
2. **Configure Options:**  
   - Toggle **Remove Comments** and **Remove Extra Empty Lines**  
   - Under **View → EOL Sequence**, choose **CRLF** or **LF**  
   - Edit **Ignore Patterns** if needed  
3. **Process:**  
   Click **Process Selected**; processed files list populates.  
4. **Preview:**  
   Select a file to view before/after code with highlighted diffs.  
5. **Undo (Session):**  
   Revert in-memory changes before saving.  
6. **Save:**  
   Click **Save All Changes** to overwrite originals (confirmation required).

## File Structure

```
Code-Finisher/
├── Ultimate_Code_Finisher.py    # Main script
├── icon.ico                     # Application icon
├── README.md                    # This file
├── requirements.txt             # PyQt6 dependency
├── dist/                        # PyInstaller output
│   └── Ultimate_Code_Finisher.exe
└── Screenshot/
    ├── Screenshot_0.png         # App screenshot
    └── Screenshot_1.png         # App uses screenshot
```

## License

MIT License © [Year] kndnsow  
Permission is hereby granted, free of charge, to any person obtaining a copy...

