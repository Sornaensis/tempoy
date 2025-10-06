#!/usr/bin/env python3
"""
Validation script for Tempoy restructured code.

This script verifies that the restructured modules work correctly and 
maintain backward compatibility. Run this after making changes to ensure
everything still works as expected.

Usage:
    python3 validate_structure.py
"""
import sys
import os

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """Test that all modules can be imported."""
    print("1. Testing module imports...")
    try:
        from models import AppConfig
        from api import JiraClient, TempoClient
        from services import ConfigManager, CONFIG_DIR, CONFIG_PATH
        print("   ✓ All modules imported successfully")
        return True
    except ImportError as e:
        print(f"   ✗ Import failed: {e}")
        return False

def test_config():
    """Test configuration functionality."""
    print("\n2. Testing configuration...")
    try:
        from models import AppConfig
        from services import ConfigManager
        
        # Test AppConfig creation
        cfg = AppConfig()
        cfg.jira_base_url = "https://test.atlassian.net"
        
        # Test serialization
        cfg_dict = cfg.to_dict()
        cfg2 = AppConfig.from_dict(cfg_dict)
        
        assert cfg2.jira_base_url == cfg.jira_base_url
        
        # Test ConfigManager.load
        loaded_cfg = ConfigManager.load()
        assert isinstance(loaded_cfg, AppConfig)
        
        print("   ✓ Configuration system works correctly")
        return True
    except Exception as e:
        print(f"   ✗ Configuration test failed: {e}")
        return False

def test_api_clients():
    """Test API client instantiation."""
    print("\n3. Testing API clients...")
    try:
        from api import JiraClient, TempoClient
        
        # Test JiraClient
        jira = JiraClient("https://test.atlassian.net", "test@example.com", "token")
        assert hasattr(jira, 'get_myself')
        assert hasattr(jira, 'search')
        assert hasattr(jira, 'search_assigned')
        
        # Test TempoClient
        tempo = TempoClient("test_token")
        assert hasattr(tempo, 'create_worklog')
        assert hasattr(tempo, 'sum_issue_times')
        assert hasattr(tempo, 'get_user_daily_total')
        
        print("   ✓ API clients work correctly")
        return True
    except Exception as e:
        print(f"   ✗ API client test failed: {e}")
        return False

def test_file_structure():
    """Test that all expected files exist."""
    print("\n4. Testing file structure...")
    try:
        expected_files = [
            'models/__init__.py',
            'models/config.py',
            'api/__init__.py',
            'api/jira_client.py',
            'api/tempo_client.py',
            'services/__init__.py',
            'services/config_service.py',
            'tempoy.py',
        ]
        
        missing = []
        for file in expected_files:
            if not os.path.exists(file):
                missing.append(file)
        
        if missing:
            print(f"   ✗ Missing files: {missing}")
            return False
        
        print("   ✓ All expected files exist")
        return True
    except Exception as e:
        print(f"   ✗ File structure test failed: {e}")
        return False

def test_syntax():
    """Test that all Python files have valid syntax."""
    print("\n5. Testing Python syntax...")
    try:
        import py_compile
        
        files = [
            'tempoy.py',
            'models/config.py',
            'api/jira_client.py',
            'api/tempo_client.py',
            'services/config_service.py',
        ]
        
        for file in files:
            py_compile.compile(file, doraise=True)
        
        print("   ✓ All files have valid syntax")
        return True
    except py_compile.PyCompileError as e:
        print(f"   ✗ Syntax error: {e}")
        return False

def main():
    """Run all tests."""
    print("=" * 60)
    print("Tempoy Structure Validation")
    print("=" * 60)
    
    tests = [
        test_imports,
        test_config,
        test_api_clients,
        test_file_structure,
        test_syntax,
    ]
    
    results = [test() for test in tests]
    
    print("\n" + "=" * 60)
    if all(results):
        print("✅ All validation tests passed!")
        print("=" * 60)
        return 0
    else:
        print("❌ Some validation tests failed!")
        print("=" * 60)
        return 1

if __name__ == "__main__":
    sys.exit(main())
