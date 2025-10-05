#!/bin/bash

# ==============================================================================
# Tempoy Cross-Platform Installation Script (macOS/Linux)
# ==============================================================================
# This script installs Tempoy with all its dependencies on macOS and Linux.
# Usage: ./install-tempoy.sh [--uninstall]

set -e

# Script configuration
SCRIPT_NAME="$(basename "$0")"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPOY_DIR="$HOME/.tempoy"
VENV_DIR="$TEMPOY_DIR/venv"
CONFIG_FILE="$TEMPOY_DIR/config.json"

# Detect OS
if [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macos"
    OS_NAME="macOS"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="linux"
    OS_NAME="Linux"
else
    echo "Error: Unsupported operating system: $OSTYPE"
    exit 1
fi

# Color codes for output
RED='\033[91m'
GREEN='\033[92m'
YELLOW='\033[93m'
BLUE='\033[94m'
RESET='\033[0m'

# Helper functions
log_step() {
    echo -e "${BLUE}$1${RESET}"
}

log_success() {
    echo -e "${GREEN}✓ $1${RESET}"
}

log_warning() {
    echo -e "${YELLOW}Warning: $1${RESET}"
}

log_error() {
    echo -e "${RED}ERROR: $1${RESET}"
}

check_command() {
    if ! command -v "$1" &> /dev/null; then
        return 1
    fi
    return 0
}

# Check for uninstall flag
if [[ "$1" == "--uninstall" ]]; then
    exec bash "$0" uninstall_tempoy
fi

if [[ "$1" == "uninstall_tempoy" ]]; then
    echo -e "${BLUE}================================================================${RESET}"
    echo -e "${BLUE}                    Tempoy Uninstallation                       ${RESET}"
    echo -e "${BLUE}================================================================${RESET}"
    echo
    echo -e "${YELLOW}This will remove Tempoy but preserve your configuration.${RESET}"
    read -p "Are you sure? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Uninstallation cancelled."
        exit 0
    fi

    echo
    log_step "Removing Tempoy installation..."

    # Remove from PATH in shell profiles
    for profile in ~/.bashrc ~/.zshrc ~/.bash_profile ~/.profile; do
        if [[ -f "$profile" ]]; then
            # Remove PATH export line for tempoy
            sed -i.bak '/# Added by Tempoy installer/d' "$profile" 2>/dev/null || true
            sed -i.bak "\|export PATH.*$TEMPOY_DIR|d" "$profile" 2>/dev/null || true
            rm -f "${profile}.bak" 2>/dev/null || true
        fi
    done

    # Remove desktop shortcut (Linux)
    if [[ "$OS" == "linux" ]]; then
        rm -f "$HOME/.local/share/applications/tempoy.desktop" 2>/dev/null || true
        # Update desktop database if available
        if check_command update-desktop-database; then
            update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
        fi
    fi

    # Remove app from Applications (macOS)
    if [[ "$OS" == "macos" ]]; then
        rm -rf "/Applications/Tempoy.app" 2>/dev/null || true
        # Remove from Launchpad database
        if check_command sqlite3; then
            local launchpad_db="$HOME/Library/Application Support/Dock/*.db"
            for db in $launchpad_db; do
                [[ -f "$db" ]] && sqlite3 "$db" "DELETE FROM apps WHERE title='Tempoy';" 2>/dev/null || true
            done
        fi
    fi

    # Remove application files but preserve config
    if [[ -d "$TEMPOY_DIR" ]]; then
        # Backup config if it exists
        if [[ -f "$CONFIG_FILE" ]]; then
            cp "$CONFIG_FILE" "$CONFIG_FILE.backup" 2>/dev/null || true
        fi
        
        # Remove everything except config files
        rm -rf "$VENV_DIR" 2>/dev/null || true
        rm -f "$TEMPOY_DIR/tempoy.py" 2>/dev/null || true
        rm -f "$TEMPOY_DIR/tempoy" 2>/dev/null || true
        
        # Restore config
        if [[ -f "$CONFIG_FILE.backup" ]]; then
            mv "$CONFIG_FILE.backup" "$CONFIG_FILE" 2>/dev/null || true
            log_success "Configuration preserved in $CONFIG_FILE"
        fi
    fi

    echo
    echo -e "${GREEN}================================================================${RESET}"
    echo -e "${GREEN}                 Uninstallation Complete!                      ${RESET}"
    echo -e "${GREEN}================================================================${RESET}"
    echo
    echo -e "${BLUE}Tempoy has been removed from your system.${RESET}"
    echo -e "${BLUE}Your configuration has been preserved in: ${RESET}$TEMPOY_DIR"
    echo
    echo -e "${YELLOW}To completely remove all traces including configuration:${RESET}"
    echo "  rm -rf \"$TEMPOY_DIR\""
    echo
    echo -e "${YELLOW}Note: You may need to restart your terminal for PATH changes to take effect.${RESET}"
    exit 0
fi

# Main installation
echo -e "${BLUE}================================================================${RESET}"
echo -e "${BLUE}                     Tempoy Installation                        ${RESET}"
echo -e "${BLUE}                         ($OS_NAME)                             ${RESET}"
echo -e "${BLUE}================================================================${RESET}"
echo

# Step 1: Check Python version
log_step "[1/8] Checking Python installation..."

PYTHON_CMD=""
for cmd in python3 python; do
    if check_command "$cmd"; then
        PYTHON_VERSION=$("$cmd" --version 2>&1 | cut -d' ' -f2)
        MAJOR=$(echo "$PYTHON_VERSION" | cut -d'.' -f1)
        MINOR=$(echo "$PYTHON_VERSION" | cut -d'.' -f2)
        
        if [[ "$MAJOR" -gt 3 || ("$MAJOR" -eq 3 && "$MINOR" -ge 8) ]]; then
            PYTHON_CMD="$cmd"
            break
        fi
    fi
done

if [[ -z "$PYTHON_CMD" ]]; then
    log_error "Python 3.8+ is required but not found."
    echo "Please install Python 3.8 or later:"
    if [[ "$OS" == "macos" ]]; then
        echo "  • Download from https://python.org"
        echo "  • Or install with Homebrew: brew install python"
    else
        echo "  • Ubuntu/Debian: sudo apt update && sudo apt install python3 python3-pip python3-venv"
        echo "  • CentOS/RHEL: sudo yum install python3 python3-pip"
        echo "  • Fedora: sudo dnf install python3 python3-pip"
        echo "  • Arch: sudo pacman -S python python-pip"
    fi
    exit 1
fi

log_success "Python $PYTHON_VERSION found ($PYTHON_CMD)"

# Step 2: Create Tempoy directory
echo
log_step "[2/8] Creating Tempoy directory..."
mkdir -p "$TEMPOY_DIR"
log_success "Directory created: $TEMPOY_DIR"

# Step 3: Create virtual environment
echo
log_step "[3/8] Creating virtual environment..."
if [[ -d "$VENV_DIR" ]]; then
    log_warning "Virtual environment already exists. Recreating..."
    rm -rf "$VENV_DIR"
fi

"$PYTHON_CMD" -m venv "$VENV_DIR"
log_success "Virtual environment created"

# Step 4: Install dependencies
echo
log_step "[4/8] Installing dependencies..."
source "$VENV_DIR/bin/activate"

# Upgrade pip first
pip install --upgrade pip > /dev/null 2>&1

# Install required packages
pip install "PySide6>=6.7" "requests>=2.32"
log_success "Dependencies installed (PySide6, requests)"

# Step 5: Copy tempoy.py
echo
log_step "[5/8] Installing Tempoy application..."
if [[ ! -f "$SCRIPT_DIR/tempoy.py" ]]; then
    log_error "tempoy.py not found in $SCRIPT_DIR"
    exit 1
fi

cp "$SCRIPT_DIR/tempoy.py" "$TEMPOY_DIR/tempoy.py"
log_success "Tempoy application installed"

# Step 6: Create launcher script
echo
log_step "[6/8] Creating launcher script..."

# Create shell launcher script
cat > "$TEMPOY_DIR/tempoy" << 'EOF'
#!/bin/bash
# Tempoy launcher script

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/venv/bin/activate"
cd "$SCRIPT_DIR"

# Run tempoy with all arguments passed through
python tempoy.py "$@"
EOF

chmod +x "$TEMPOY_DIR/tempoy"
log_success "Launcher script created"

# Step 7: System integration
echo
log_step "[7/8] Setting up system integration..."

# Add to PATH by updating shell profiles
PATH_ADDED=false
for profile in ~/.bashrc ~/.zshrc ~/.bash_profile ~/.profile; do
    if [[ -f "$profile" ]]; then
        # Check if already in PATH
        if ! grep -q "export PATH.*$TEMPOY_DIR" "$profile" 2>/dev/null; then
            echo "" >> "$profile"
            echo "# Added by Tempoy installer" >> "$profile"
            echo "export PATH=\"$TEMPOY_DIR:\$PATH\"" >> "$profile"
            PATH_ADDED=true
        fi
    fi
done

# If no profile exists, create ~/.profile
if [[ "$PATH_ADDED" == false ]]; then
    echo "# Added by Tempoy installer" >> ~/.profile
    echo "export PATH=\"$TEMPOY_DIR:\$PATH\"" >> ~/.profile
    PATH_ADDED=true
fi

# Platform-specific integration
if [[ "$OS" == "macos" ]]; then
    # Create macOS app bundle
    APP_DIR="/Applications/Tempoy.app"
    CONTENTS_DIR="$APP_DIR/Contents"
    MACOS_DIR="$CONTENTS_DIR/MacOS"
    RESOURCES_DIR="$CONTENTS_DIR/Resources"
    
    sudo mkdir -p "$MACOS_DIR" "$RESOURCES_DIR" 2>/dev/null || {
        # Fallback to user Applications
        APP_DIR="$HOME/Applications/Tempoy.app"
        CONTENTS_DIR="$APP_DIR/Contents"
        MACOS_DIR="$CONTENTS_DIR/MacOS"
        RESOURCES_DIR="$CONTENTS_DIR/Resources"
        mkdir -p "$MACOS_DIR" "$RESOURCES_DIR"
    }
    
    # Create Info.plist
    cat > "$CONTENTS_DIR/Info.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>tempoy</string>
    <key>CFBundleIdentifier</key>
    <string>com.tempoy.app</string>
    <key>CFBundleName</key>
    <string>Tempoy</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.15</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
EOF
    
    # Create launcher executable
    cat > "$MACOS_DIR/tempoy" << EOF
#!/bin/bash
export PATH="$TEMPOY_DIR:\$PATH"
cd "$TEMPOY_DIR"
source venv/bin/activate
python tempoy.py
EOF
    chmod +x "$MACOS_DIR/tempoy"
    
elif [[ "$OS" == "linux" ]]; then
    # Create desktop entry for Linux
    DESKTOP_FILE="$HOME/.local/share/applications/tempoy.desktop"
    mkdir -p "$(dirname "$DESKTOP_FILE")"
    
    cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Tempoy
Comment=Time logging for Jira and Tempo
Exec=$TEMPOY_DIR/tempoy
Icon=applications-office
Terminal=false
Categories=Office;Productivity;
StartupWMClass=tempoy
EOF
    
    chmod +x "$DESKTOP_FILE"
    
    # Update desktop database if available
    if check_command update-desktop-database; then
        update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
    fi
fi

log_success "System integration completed"

# Step 8: Test installation
echo
log_step "[8/8] Testing installation..."

cd "$TEMPOY_DIR"
source venv/bin/activate

# Test by checking if modules load correctly
if python -c "import sys; sys.path.insert(0, '.'); import tempoy" 2>/dev/null; then
    log_success "Installation verified"
else
    log_warning "Could not fully verify installation, but files are in place."
fi

# Preserve existing config
if [[ -f "$CONFIG_FILE" ]]; then
    log_success "Existing configuration preserved"
fi

# Installation complete
echo
echo -e "${GREEN}================================================================${RESET}"
echo -e "${GREEN}                  Installation Complete!                        ${RESET}"
echo -e "${GREEN}================================================================${RESET}"
echo
echo -e "${BLUE}Tempoy has been installed to: ${RESET}$TEMPOY_DIR"
echo

echo -e "${BLUE}To run Tempoy:${RESET}"
if [[ "$OS" == "macos" ]]; then
    echo "  • From Applications: Open Tempoy.app"
    echo "  • From Spotlight: Search for \"Tempoy\""
elif [[ "$OS" == "linux" ]]; then
    echo "  • From desktop: Search for \"Tempoy\" in applications"
    echo "  • From terminal: ${YELLOW}tempoy${RESET} (after restarting terminal)"
fi
echo "  • Directly: ${YELLOW}$TEMPOY_DIR/tempoy${RESET}"
echo

echo -e "${BLUE}To uninstall:${RESET}"
echo "  • Run: ${YELLOW}$0 --uninstall${RESET}"
echo

echo -e "${BLUE}Configuration will be stored in:${RESET}"
echo "  $CONFIG_FILE"
echo

echo -e "${YELLOW}Note: You may need to restart your terminal to use the 'tempoy' command.${RESET}"
echo

exit 0