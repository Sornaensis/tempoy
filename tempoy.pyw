#!/usr/bin/env python3
"""
Tempoy - Time tracking application launcher (no console window)

This is a .pyw file that runs the Tempoy application without showing a console window.
Use this instead of tempoy.py to avoid console window issues on Windows.
"""

# Import and run the main application
if __name__ == "__main__":
    from tempoy import main
    main()