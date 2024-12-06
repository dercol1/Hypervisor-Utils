VMStats - Hypervisor Information Collector
VMStats is a collection of Python scripts designed to gather and display detailed information about virtual machines and hosts from various hypervisor platforms. The tool provides an interactive terminal interface for viewing and exporting data.
Features

    Support for multiple hypervisor platforms (Proxmox, oVirt/RHV, VMware)
    Interactive terminal UI with navigation and search capabilities
    Data export in multiple formats (Excel, CSV, HTML)
    Detailed host hardware information collection
    Network interface and storage details
    Tree-view display for host information
    Search functionality within data
    Page Up/Down navigation

Scripts
The repository contains three main scripts:
1. getkclivm.py
Main script supporting multiple hypervisors with advanced features:
bash

./getkclivm.py --provider <provider> --url <url> --username <user> --password <password>

# Example for Proxmox:
./getkclivm.py --provider proxmox --url https://proxmox.example.com:8006 --username user@pve --password 'password'

2. getovirtvm.py
Specialized script for oVirt/RHV environments:
bash

./getovirtvm.py --url https://ovirt.example.com/ovirt-engine/api --username user@domain --password 'password'

3. getproxmoxvm.py
Dedicated script for Proxmox environments:
bash

./getproxmoxvm.py --host proxmox.example.com --username user@pve --password 'password'

Installation

    Create and activate a Python virtual environment:

bash

python3 -m venv python-venv
source python-venv/bin/activate  # Linux/Mac
python-venv\Scripts\activate     # Windows

    Install required packages:

bash

pip install pandas tabulate proxmoxer requests ovirtsdk4 pyvmomi

Usage
Interactive Navigation

    Arrow keys: Navigate through data
    Page Up/Down: Scroll page by page
    Enter: Expand/collapse nodes in tree view
    '/': Enter search mode
    'n': Next search result
    'p': Previous search result
    's': Save current view to file
    'q': Exit current view

Data Export
All scripts support exporting data in multiple formats:

    Excel (.xlsx)
    CSV (.csv)
    HTML (.html)

Supported Hypervisors

    Proxmox VE
    oVirt/RHV
    VMware vSphere
    (Additional hypervisors can be added through the main script)

Notes

    For Proxmox, ensure proper user permissions for system commands
    SSL verification is disabled by default for testing
    Some features may require specific API access rights
    All scripts support both interactive and command-line modes

Requirements

    Python 3.6+
    Curses library (included in Python for Unix systems, separate installation needed for Windows)
    Network access to hypervisor management interfaces
