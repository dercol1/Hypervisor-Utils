#!/usr/bin/env python3

import os
import sys
import argparse
from datetime import datetime
import pandas as pd
from proxmoxer import ProxmoxAPI
import requests
from tabulate import tabulate
import curses
import json

# Disabilita i proxy a livello di ambiente
os.environ.pop('http_proxy', None)
os.environ.pop('https_proxy', None)
os.environ.pop('HTTP_PROXY', None)
os.environ.pop('HTTPS_PROXY', None)


def get_input(prompt):
    return input(prompt)


def interactive_menu():
    print("\n=== Proxmox VM Reporter ===")
    host = get_input("Inserisci l'hostname del server Proxmox: ")
    username = get_input("Inserisci username (formato: user@pve): ")
    password = get_input("Inserisci password: ")
    output_file = get_input(
        "Inserisci il nome del file di output (lascia vuoto per visualizzazione interattiva): ")
    return host, username, password, output_file


def get_vm_info(proxmox):
    vm_list = []

    for node in proxmox.nodes.get():
        node_name = node['node']

        for vm in proxmox.nodes(node_name).qemu.get():
            config = proxmox.nodes(node_name).qemu(vm['vmid']).config.get()

            network_interfaces = {}
            for key, value in config.items():
                if key.startswith('net'):
                    network_interfaces[key] = value

            vm_info = {
                'Nome': vm['name'],
                'ID': vm['vmid'],
                'Status': vm['status'],
                'CPU': vm['cpus'],
                'Memoria (MB)': vm['maxmem'] / (1024*1024),
                'Disco (GB)': vm.get('maxdisk', 0) / (1024*1024*1024),
                'Node': node_name,
                'Uptime': vm.get('uptime', 0),
                'Template': vm.get('template', False),
                'OS Type': config.get('ostype', 'N/A'),
                'BIOS': config.get('bios', 'N/A'),
                'Boot Order': config.get('boot', 'N/A'),
                'Network Interfaces': json.dumps(network_interfaces),
                'CPU Type': config.get('cpu', 'N/A'),
                'Machine': config.get('machine', 'N/A'),
                'SCSI Hardware': config.get('scsihw', 'N/A'),
                'VGA': config.get('vga', 'N/A')
            }
            vm_list.append(vm_info)

    return vm_list


def save_data(stdscr, data):
    stdscr.clear()
    curses.echo()
    stdscr.addstr(
        0, 0, "Inserisci il nome del file (con estensione .xlsx, .csv o .html): ")
    filename = stdscr.getstr().decode('utf-8')
    curses.noecho()

    try:
        export_data(data, filename)
        stdscr.addstr(2, 0, f"File salvato come: {filename}")
        stdscr.addstr(3, 0, "Premi un tasto per continuare...")
        stdscr.refresh()
        stdscr.getch()
    except Exception as e:
        stdscr.addstr(2, 0, f"Errore nel salvataggio: {str(e)}")
        stdscr.addstr(3, 0, "Premi un tasto per continuare...")
        stdscr.refresh()
        stdscr.getch()


def display_interactive_table(data):
    def show_table(stdscr, data, current_row, current_col):
        stdscr.clear()
        height, width = stdscr.getmaxyx()

        df = pd.DataFrame(data)
        table_str = tabulate(df.iloc[current_row:current_row+height-2],
                             headers='keys',
                             tablefmt='grid',
                             showindex=False)

        table_lines = table_str.split('\n')
        for i, line in enumerate(table_lines):
            if i < height-1:
                if len(line) > current_col:
                    stdscr.addstr(i, 0, line[current_col:current_col+width-1])

        # Aggiungi istruzioni
        help_text = "Usa frecce per navigare, 's' per salvare, 'q' per uscire"
        stdscr.addstr(height-1, 0, help_text[:width-1])
        stdscr.refresh()
        return len(df), len(table_lines[0]) if table_lines else 0

    def main(stdscr, data):
        curses.use_default_colors()
        current_row = 0
        current_col = 0

        while True:
            total_rows, max_width = show_table(
                stdscr, data, current_row, current_col)
            key = stdscr.getch()

            if key == curses.KEY_UP and current_row > 0:
                current_row -= 1
            elif key == curses.KEY_DOWN and current_row < total_rows-1:
                current_row += 1
            elif key == curses.KEY_LEFT and current_col > 0:
                current_col -= 3
            elif key == curses.KEY_RIGHT and current_col < max_width:
                current_col += 3
            elif key == ord('s'):
                save_data(stdscr, data)
            elif key == ord('q'):
                break

            current_col = max(0, current_col)

    curses.wrapper(main, data)


def export_data(data, filename):
    df = pd.DataFrame(data)

    if filename.lower().endswith('.xlsx'):
        df.to_excel(filename, index=False)
    elif filename.lower().endswith('.csv'):
        df.to_csv(filename, index=False)
    elif filename.lower().endswith('.html'):
        df.to_html(filename, index=False)
    else:
        raise ValueError(
            "Formato file non supportato. Usa .xlsx, .csv o .html")


def main():
    parser = argparse.ArgumentParser(description='Proxmox VM Reporter')
    parser.add_argument('--host', help='Proxmox host')
    parser.add_argument('--username', help='Username (format: user@pve)')
    parser.add_argument('--password', help='Password')
    parser.add_argument('--output', help='Output file (xlsx/csv/html)')

    args = parser.parse_args()

    if not all([args.host, args.username, args.password]):
        host, username, password, output_file = interactive_menu()
    else:
        host = args.host
        username = args.username
        password = args.password
        output_file = args.output

    proxmox = ProxmoxAPI(host,
                         user=username,
                         password=password,
                         verify_ssl=False)

    vm_data = get_vm_info(proxmox)

    if output_file:
        export_data(vm_data, output_file)
        print(f"Report salvato come: {output_file}")
    else:
        display_interactive_table(vm_data)


if __name__ == "__main__":
    main()
