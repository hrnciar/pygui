# GDB GUI

A graphical debugger interface for GDB written in Python, designed to complement the command line and TUI interfaces.

## Overview

This is a proof-of-concept GUI for GDB that leverages the GDB Python API to provide a modern debugging experience. It runs alongside GDB and provides visual representations of your debugging session including source code, disassembly, breakpoints, stack frames, and local variables.

## Features

- **Source Code View**: Display and navigate source code for the current debugging context
- **Disassembly View**: Toggle between source and assembly views to see the low-level instruction execution
- **Interactive Breakpoints**: Set and remove breakpoints by clicking on line numbers in the source view
- **Stack Frame Navigation**: Browse the call stack and inspect different frames
- **Local Variables Inspection**: View local variables and their values in the current frame
- **Breakpoint Management**: Visual list of all breakpoints with their locations and status
- **Toolbar Controls**: Quick access to common debugging operations:
  - Run/Continue
  - Interrupt
  - Step/Next (source level)
  - Stepi/Nexti (instruction level)
  - Finish (step out)
- **State-Aware UI**: Buttons enable/disable based on the current program state (idle/running/stopped)

## Requirements

- GDB with Python support (GDB 7.0 or later recommended)
- Python 3.x
- tkinter (usually included with Python)

**No external dependencies required** - the project uses only Python standard library components.

## Installation

1. Clone this repository:
   ```bash
   git clone <repository-url>
   cd gdb-gui
   ```

2. The main file `pygui.py` needs to be sourced in GDB.

## Usage

### Loading the GUI

Start GDB and source the script:

```bash
gdb <your-program>
```

Then in the GDB prompt:

```
(gdb) source /path/to/pygui.py
(gdb) gui enable
```

### GDB Commands

The following commands are available once the script is loaded:

- `gui enable` - Open/show the GUI window
- `gui disable` - Close the GUI window

## Development

This is currently a proof of concept with a limited feature set. Contributions and suggestions are welcome!

## License

This program is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation; either version 3 of the License, or (at your option) any later version.

See the source code header for the complete license text.

## Contributing

Contributions are welcome! Please feel free to submit pull requests or open issues for bugs and feature requests.
