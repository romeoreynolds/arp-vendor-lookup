import requests
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

# Function to query the MAC Address Lookup API
def lookup_mac(mac_address):
    url = f"https://www.macvendorlookup.com/api/v2/{mac_address}"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            if data:
                return data[0].get("company", "Unknown")
        return "Unknown"
    except Exception as e:
        print(f"Error fetching MAC vendor for {mac_address}: {e}")
        return "Unknown"

# Function to parse ARP table and lookup MAC vendors
def process_arp_table():
    arp_data = arp_input.get("1.0", tk.END).strip()  # Get text from input field
    lines = arp_data.splitlines()
    
    results = []
    results.append(f"{'IP Address':<15} {'MAC Address':<20} {'Company Name':<40}")
    results.append("=" * 75)

    for line in lines:
        parts = line.split()
        if len(parts) >= 4:
            ip = parts[0]
            mac = parts[3]
            if mac != "00:00:00:00:00:00":  # Exclude invalid MACs
                company_name = lookup_mac(mac)
                results.append(f"{ip:<15} {mac:<20} {company_name:<40}")
    
    # Display results in the output area
    output_text.delete("1.0", tk.END)
    output_text.insert(tk.END, "\n".join(results))

# Create the GUI
def create_gui():
    root = tk.Tk()
    root.title("ARP Table Processor")

    # Input Label and Text Area
    input_label = ttk.Label(root, text="Paste ARP Table:")
    input_label.pack(pady=5)

    global arp_input
    arp_input = ScrolledText(root, wrap=tk.WORD, height=10, width=80)
    arp_input.pack(padx=10, pady=5)

    # Process Button
    process_button = ttk.Button(root, text="Process ARP Table", command=process_arp_table)
    process_button.pack(pady=10)

    # Output Label and Text Area
    output_label = ttk.Label(root, text="Results:")
    output_label.pack(pady=5)

    global output_text
    output_text = ScrolledText(root, wrap=tk.WORD, height=15, width=80, state=tk.NORMAL)
    output_text.pack(padx=10, pady=5)

    # Start the GUI main loop
    root.mainloop()

# Run the GUI
if __name__ == "__main__":
    create_gui()
    