# Code Cleaner (Internal Tools)

A simple desktop application built with Python and Tkinter to clean up code files by removing comments and extra blank lines, normalizing line endings, and performing basic JSON/XML pretty-printing. This version uses only internal Python logic, requiring no external formatter installations.

![Application Screenshot](https://github.com/user-attachments/assets/ca1cfa1a-5965-420c-a475-4f9dec91ff7d) 

## Features

*   **File/Directory Selection:** Process individual code files or entire project directories recursively.
*   **Language Support:** Handles common comment styles for various languages (Python, JS, Java, C++, C#, PHP, HTML, CSS, XML, etc.). (*Note: Based on regex, may have limitations*).
*   **Comment Removal:** Option to strip single-line and multi-line comments.
*   **Empty Line Removal:** Option to consolidate multiple blank lines into a single blank line.
*   **EOL Normalization:** Set file line endings to CRLF (Windows) or LF (Unix/macOS).
*   **Basic Formatting:** Pretty-prints JSON and XML files.
*   **Ignore Patterns:** Specify file/directory patterns (like `.git/`, `node_modules/`, `*.log`) to exclude from processing. Uses Glob patterns.
*   **Dark Theme:** Fixed dark user interface for comfortable viewing.
*   **Preview:** Side-by-side "Before" and "After" preview panes with difference highlighting.
*   **Undo (Session):** Revert changes made during the last processing run (before saving).
*   **Save:** Overwrite original files with the cleaned versions.
*   **Responsive UI:** Application window starts maximized.
*   **Threading:** Background processing prevents the UI from freezing on larger tasks.

## Usage

### Running from Source

1.  Ensure you have Python 3 installed.
2.  No external libraries beyond the standard library are required for basic operation.
3.  Run the script:
    ```bash
    python Ultimate_Code_Finisher.py
    ```

### Using the Executable (`.exe`)

*(If you distribute the built executable)*

1.  Download `Ultimate_Code_Finisher.exe`.
2.  Double-click the `.exe` file to run the application. No installation is needed.

### How to Use the Application

1.  **Select Source:** Click "Select File..." or "Select Directory..." to choose the code you want to process.
2.  **Set Options:**
    *   Check/uncheck "Remove Comments" and "Remove Extra Empty Lines".
    *   Use the "View" -> "EOL Sequence" menu to choose CRLF (Windows) or LF (Unix/Mac) line endings for saved files.
    *   Modify the "Ignore Patterns (Glob)" list if needed. Add one pattern per line (e.g., `dist/`, `*.tmp`).
3.  **Process:** Click "Process Selected". The application will scan the selection, process matching files according to options, and populate the "Processed Files" list (using relative paths if a directory was selected).
4.  **Preview:** Click on a file in the "Processed Files" list to view the "Before" and "After" comparison. Differences are highlighted (red background for removed lines in "Before", green for added/modified in "After").
5.  **Undo (Optional):** If you want to discard the changes from the *last* processing run, click "Undo All (Session)".
6.  **Save:** If you are satisfied with the preview, click "Save All Changes". **This will overwrite the original files.** You will be asked for confirmation.

## File Structure

```
./
├── Ultimate_Code_Finisher.py    # Main Python script
├── icon.ico                     # Application icon
├── README.md                    # This README file
├── test/                        # Directory containing test files (optional)
│   ├── test_python.py
│   ├── test_javascript.js
│   └── ...
├── build/                       # PyInstaller build directory (generated)
├── dist/                        # PyInstaller distribution directory (generated)
│   └── Ultimate_Code_Finisher.exe # The executable
└── Ultimate_Code_Finisher.spec  # PyInstaller spec file (generated)
```

## Building with PyInstaller

To create the standalone `.exe` file, you need PyInstaller:

```bash
pip install pyinstaller
```

Then, run the following command from the project's root directory (where the `.py` script and `icon.ico` are located):

```bash
pyinstaller --onefile --add-data "icon.ico;." --windowed --icon=icon.ico Ultimate_Code_Finisher.py
```

*   `--onefile`: Creates a single executable file.
*   `--add-data "icon.ico;."`: Bundles the `icon.ico` file into the executable. The `;.` tells PyInstaller to place it in the root directory inside the bundle relative to the executable.
*   `--windowed`: Prevents a console window from appearing when the GUI application runs.
*   `--icon=icon.ico`: Sets the icon for the executable file itself.

The executable will be located in the `dist` directory.

## Limitations

*   **Comment Removal:** Uses regular expressions, which may not perfectly handle all edge cases (e.g., comment markers within string literals).
*   **Formatting:** Only basic JSON and XML pretty-printing is included. Advanced code formatting (like PEP 8 compliance, complex spacing rules) is not performed.
*   **UI Styling:** The appearance (especially menus and window title bar) may vary slightly depending on your Operating System, as some elements are drawn by the OS.

## License

*(Optional: Add license information here, e.g., MIT License)*

```
MIT License

Copyright (c) [Year] [Your Name/Organization]

Permission is hereby granted... (full MIT license text) ...
```
