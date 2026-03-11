#!/bin/bash

# ==============================================================================
# Tempoy Cross-Platform Startup Registration Script (macOS/Linux)
# ==============================================================================
# This script registers Tempoy to start automatically on login.
# Usage: ./autostart-tempoy.sh [--enable|--disable|--status|--help]

set -e

# Script configuration
SCRIPT_NAME="$(basename "$0")"
TEMPOY_DIR="$HOME/.tempoy"
TEMPOY_LAUNCHER="$TEMPOY_DIR/tempoy"
TEMPOY_PACKAGE_DIR="$TEMPOY_DIR/tempoy_app"

# Detect OS
if [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macos"
    OS_NAME="macOS"
    AUTOSTART_DIR="$HOME/Library/LaunchAgents"
    AUTOSTART_FILE="$AUTOSTART_DIR/com.tempoy.agent.plist"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS="linux"
    OS_NAME="Linux"
    AUTOSTART_DIR="$HOME/.config/autostart"
    AUTOSTART_FILE="$AUTOSTART_DIR/tempoy.desktop"
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
    echo -e "${YELLOW}○ $1${RESET}"
}

log_error() {
    echo -e "${RED}✗ $1${RESET}"
}

check_command() {
    if ! command -v "$1" &> /dev/null; then
        return 1
    fi
    return 0
}

show_help() {
    echo -e "${BLUE}Tempoy Startup Registration Script ($OS_NAME)${RESET}"
    echo
    echo -e "${BLUE}Usage:${RESET}"
    echo "  $SCRIPT_NAME [--enable|--disable|--status|--help]"
    echo
    echo -e "${BLUE}Options:${RESET}"
    echo "  --enable    Enable Tempoy autostart (default)"
    echo "  --disable   Disable Tempoy autostart"
    echo "  --status    Show current autostart status"
    echo "  --help      Show this help message"
    echo
    echo -e "${BLUE}Examples:${RESET}"
    echo "  $SCRIPT_NAME           (enables autostart)"
    echo "  $SCRIPT_NAME --enable  (enables autostart)"
    echo "  $SCRIPT_NAME --disable (disables autostart)"
    echo "  $SCRIPT_NAME --status  (shows status)"
    echo
    echo -e "${BLUE}Description:${RESET}"
    echo "  This script manages Tempoy's automatic startup on login."
    if [[ "$OS" == "macos" ]]; then
        echo "  On macOS, it creates a LaunchAgent plist file."
        echo "  File location: $AUTOSTART_FILE"
    else
        echo "  On Linux, it creates a desktop autostart entry."
        echo "  File location: $AUTOSTART_FILE"
    fi
    echo
}

check_tempoy_installation() {
    if [[ ! -f "$TEMPOY_LAUNCHER" ]]; then
        log_error "Tempoy is not installed."
        echo "Please run install-tempoy.sh first."
        echo "Expected launcher: $TEMPOY_LAUNCHER"
        exit 1
    fi

    if [[ ! -d "$TEMPOY_DIR" ]]; then
        log_error "Tempoy installation directory not found: $TEMPOY_DIR"
        echo "Please reinstall Tempoy."
        exit 1
    fi
}

create_macos_autostart() {
    log_step "Creating macOS LaunchAgent..."
    
    # Create LaunchAgents directory if it doesn't exist
    mkdir -p "$AUTOSTART_DIR"
    
    # Create the plist file
    cat > "$AUTOSTART_FILE" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.tempoy.agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>$TEMPOY_LAUNCHER</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>LaunchOnlyOnce</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$HOME/Library/Logs/tempoy.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/Library/Logs/tempoy.log</string>
    <key>WorkingDirectory</key>
    <string>$TEMPOY_DIR</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>$TEMPOY_DIR:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
EOF

    # Set appropriate permissions
    chmod 644 "$AUTOSTART_FILE"
    log_success "LaunchAgent plist created: $AUTOSTART_FILE"
    
    # Load the agent
    if launchctl load "$AUTOSTART_FILE" 2>/dev/null; then
        log_success "LaunchAgent loaded successfully"
    else
        log_warning "LaunchAgent created but could not be loaded immediately"
        echo "It will be loaded on next login."
    fi
}

create_linux_autostart() {
    log_step "Creating Linux autostart entry..."
    
    # Create autostart directory if it doesn't exist
    mkdir -p "$AUTOSTART_DIR"
    
    # Create the desktop file
    cat > "$AUTOSTART_FILE" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Tempoy
Comment=Automatic time logging for Jira and Tempo
Exec=$TEMPOY_LAUNCHER
Icon=applications-office
Terminal=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
Categories=Office;Productivity;
StartupWMClass=tempoy
EOF

    # Set appropriate permissions
    chmod +x "$AUTOSTART_FILE"
    log_success "Autostart entry created: $AUTOSTART_FILE"
}

enable_autostart() {
    echo -e "${BLUE}================================================================${RESET}"
    echo -e "${BLUE}                 Enabling Tempoy Autostart                     ${RESET}"
    echo -e "${BLUE}                        ($OS_NAME)                             ${RESET}"
    echo -e "${BLUE}================================================================${RESET}"
    echo

    check_tempoy_installation

    # Check if already enabled
    if [[ -f "$AUTOSTART_FILE" ]]; then
        log_warning "Autostart is already enabled."
        echo
        echo -e "${BLUE}Current configuration:${RESET}"
        echo "  File: $AUTOSTART_FILE"
        echo
        read -p "Update the configuration? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Configuration unchanged."
            return
        fi
    fi

    # Create platform-specific autostart
    if [[ "$OS" == "macos" ]]; then
        create_macos_autostart
    else
        create_linux_autostart
    fi

    # Verify creation
    if [[ -f "$AUTOSTART_FILE" ]]; then
        log_success "Autostart configuration created successfully"
        
        # Test the launcher
        echo
        log_step "Testing launcher..."
        if [[ -x "$TEMPOY_LAUNCHER" ]]; then
            log_success "Launcher script is executable"
            
            # Quick test - check if dependencies are available
            cd "$TEMPOY_DIR"
            if source venv/bin/activate 2>/dev/null && python -c "import tempoy; import tempoy_app" 2>/dev/null; then
                log_success "Tempoy dependencies verified"
            else
                log_warning "Could not verify Tempoy dependencies"
                echo "Autostart is configured but may not work properly."
            fi
        else
            log_error "Launcher script is not executable: $TEMPOY_LAUNCHER"
            exit 1
        fi
    else
        log_error "Failed to create autostart configuration"
        exit 1
    fi

    echo
    echo -e "${GREEN}================================================================${RESET}"
    echo -e "${GREEN}              Autostart Successfully Enabled!                  ${RESET}"
    echo -e "${GREEN}================================================================${RESET}"
    echo
    echo -e "${BLUE}Tempoy will now start automatically when you log in.${RESET}"
    
    if [[ "$OS" == "macos" ]]; then
        echo
        echo -e "${BLUE}macOS specific notes:${RESET}"
        echo "• LaunchAgent will start Tempoy on login"
        echo "• Logs are written to: ~/Library/Logs/tempoy.log"
        echo "• You can manually start with: launchctl start com.tempoy.agent"
    else
        echo
        echo -e "${BLUE}Linux specific notes:${RESET}"
        echo "• Desktop entry created in ~/.config/autostart/"
        echo "• Tempoy will appear in your desktop environment's startup applications"
    fi
    
    echo
    echo -e "${BLUE}To disable autostart:${RESET}"
    echo "  $0 --disable"
    echo
    echo -e "${BLUE}To check status:${RESET}"
    echo "  $0 --status"
}

disable_autostart() {
    echo -e "${BLUE}================================================================${RESET}"
    echo -e "${BLUE}                Disabling Tempoy Autostart                     ${RESET}"
    echo -e "${BLUE}                        ($OS_NAME)                             ${RESET}"
    echo -e "${BLUE}================================================================${RESET}"
    echo

    # Check if currently enabled
    if [[ ! -f "$AUTOSTART_FILE" ]]; then
        log_warning "Autostart is not currently enabled."
        return
    fi

    log_step "Removing autostart configuration..."

    # Platform-specific cleanup
    if [[ "$OS" == "macos" ]]; then
        # Unload the agent first
        if launchctl list | grep -q "com.tempoy.agent" 2>/dev/null; then
            launchctl unload "$AUTOSTART_FILE" 2>/dev/null || true
            log_success "LaunchAgent unloaded"
        fi
    fi

    # Remove the autostart file
    if rm -f "$AUTOSTART_FILE" 2>/dev/null; then
        log_success "Autostart configuration removed"
    else
        log_error "Failed to remove autostart configuration"
        exit 1
    fi

    # Verify removal
    if [[ ! -f "$AUTOSTART_FILE" ]]; then
        log_success "Autostart disabled and verified"
    else
        log_warning "Autostart file may still exist"
    fi

    echo
    echo -e "${GREEN}================================================================${RESET}"
    echo -e "${GREEN}              Autostart Successfully Disabled!                 ${RESET}"
    echo -e "${GREEN}================================================================${RESET}"
    echo
    echo -e "${BLUE}Tempoy will no longer start automatically on login.${RESET}"
    echo -e "${BLUE}You can still run it manually from applications or command line.${RESET}"
}

show_status() {
    echo -e "${BLUE}================================================================${RESET}"
    echo -e "${BLUE}                  Tempoy Autostart Status                      ${RESET}"
    echo -e "${BLUE}                        ($OS_NAME)                             ${RESET}"
    echo -e "${BLUE}================================================================${RESET}"
    echo

    log_step "Checking autostart configuration..."
    echo

    # Check if autostart file exists
    if [[ -f "$AUTOSTART_FILE" ]]; then
        log_success "Autostart is ENABLED"
        echo
        echo -e "${BLUE}Configuration details:${RESET}"
        echo "  File: $AUTOSTART_FILE"
        echo "  Type: $([[ "$OS" == "macos" ]] && echo "LaunchAgent plist" || echo "Desktop autostart entry")"
        
        # Show file modification time
        if [[ "$OS" == "macos" ]]; then
            echo "  Modified: $(stat -f "%Sm" -t "%Y-%m-%d %H:%M:%S" "$AUTOSTART_FILE" 2>/dev/null || echo "Unknown")"
        else
            echo "  Modified: $(stat -c "%y" "$AUTOSTART_FILE" 2>/dev/null | cut -d'.' -f1 || echo "Unknown")"
        fi
        
        # Platform-specific status
        if [[ "$OS" == "macos" ]]; then
            echo
            echo -e "${BLUE}LaunchAgent status:${RESET}"
            if launchctl list | grep -q "com.tempoy.agent" 2>/dev/null; then
                log_success "LaunchAgent is loaded"
            else
                log_warning "LaunchAgent is not currently loaded"
                echo "  It will be loaded on next login."
            fi
        fi
        
    else
        log_warning "Autostart is DISABLED"
        echo
        echo -e "${BLUE}To enable autostart:${RESET}"
        echo "  $0 --enable"
    fi

    echo
    log_step "Checking Tempoy installation..."
    
    # Check Tempoy installation
    if [[ -f "$TEMPOY_LAUNCHER" ]]; then
        log_success "Launcher script exists: $TEMPOY_LAUNCHER"
        
        if [[ -x "$TEMPOY_LAUNCHER" ]]; then
            log_success "Launcher script is executable"
        else
            log_error "Launcher script is not executable"
        fi
    else
        log_error "Launcher script missing: $TEMPOY_LAUNCHER"
        echo "  Autostart may not work. Try reinstalling Tempoy."
    fi

    if [[ -d "$TEMPOY_DIR" ]]; then
        log_success "Tempoy installation found: $TEMPOY_DIR"
        
        # Check if virtual environment exists
        if [[ -d "$TEMPOY_DIR/venv" ]]; then
            log_success "Virtual environment found"
        else
            log_error "Virtual environment missing"
        fi
        
        # Check if tempoy.py exists
        if [[ -f "$TEMPOY_DIR/tempoy.py" ]]; then
            log_success "Tempoy application found"
        else
            log_error "Tempoy application missing"
        fi

        if [[ -d "$TEMPOY_PACKAGE_DIR" ]]; then
            log_success "Tempoy package found"
        else
            log_error "Tempoy package missing"
        fi
        
    else
        log_error "Tempoy installation missing: $TEMPOY_DIR"
        echo "  Please reinstall Tempoy."
    fi

    # Check if currently running
    echo
    echo -e "${BLUE}Current status:${RESET}"
    if pgrep -f "python.*(tempoy.py|-m tempoy_app)" > /dev/null 2>&1; then
        log_success "Tempoy appears to be running"
    else
        log_warning "Tempoy does not appear to be running"
    fi
}

# Main script logic
ACTION="enable"

# Parse command line arguments
case "$1" in
    --enable)
        ACTION="enable"
        ;;
    --disable)
        ACTION="disable"
        ;;
    --status)
        ACTION="status"
        ;;
    --help|-h)
        show_help
        exit 0
        ;;
    "")
        ACTION="enable"
        ;;
    *)
        echo "Error: Unknown option '$1'"
        echo "Use --help for usage information."
        exit 1
        ;;
esac

# Execute the requested action
case "$ACTION" in
    enable)
        enable_autostart
        ;;
    disable)
        disable_autostart
        ;;
    status)
        show_status
        ;;
esac

exit 0