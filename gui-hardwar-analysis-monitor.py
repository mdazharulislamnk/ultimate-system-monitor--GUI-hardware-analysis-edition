"""
SYSTEM MONITOR PRO - HARDWARE ANALYSIS EDITION
Author: Md. Azharul Islam
License: MIT

Description:
    A professional-grade system diagnostics and monitoring dashboard.
    
    This "Hardware Analysis" edition focuses on deep introspection of components:
    1. CPU: Real-time Load, Clock Speed, and Per-Core utilization.
    2. RAM: Brand, Speed, and exact usage breakdown.
    3. STORAGE: Physical Drive Models (e.g., Samsung SSD) & Logical Partitions.
       - Includes "Marketing Size" logic (3.64 TiB -> 4.0 TB).
    4. MOTHERBOARD: Scrapes Windows Registry to find Manufacturer/Model without Admin rights.
    5. TEMPERATURE: Uses a multi-stage probe (WMI, PerfCounters, OHM) to find thermal data.

    Architecture:
    - Threading: Network calls (Ping) run in background threads to prevent GUI freezing.
    - CustomTkinter: Provides the modern, High-DPI, Dark-Mode interface.
    - Registry/WMI: Used for hardware scraping without requiring Administrator privileges.
"""

# ==========================================
# 📚 LIBRARIES & MODULES
# ==========================================
import customtkinter as ctk  # UI Framework for modern, rounded, dark-themed widgets
import psutil                # The core engine for fetching CPU/RAM/Disk usage stats
import threading             # Allows running blocking tasks (like Ping) in the background
import socket                # Used for raw TCP connections to measure network latency
import platform              # Retrieves basic OS and Hostname information
import time                  # Used for timing loops and delays
import subprocess            # Executes Windows Shell commands (PowerShell/WMIC)
import sys                   # System parameters
import ctypes                # Interfaces with Windows API (Screen size, etc.)
import csv                   # Parses command output data
import io                    # Handles string streams for CSV parsing
import math                  # Used for size calculations
import winreg                # Access Windows Registry (Key for Motherboard info without Admin)
from datetime import datetime # Used to format the System Uptime

# ==========================================
# ⚙️ CONFIGURATION (USER SETTINGS)
# ==========================================
APP_TITLE = "System Monitor Pro: Hardware Analysis Edition By Azhar"

# Window Dimensions
APP_SIZE = "1360x950" 
# Window Start Position (Pixels from Top-Left)
WINDOW_X = 50
WINDOW_Y = 50
# How often to refresh data (1000ms = 1 second)
REFRESH_RATE = 1000 

# --- COLOR PALETTE (Cyberpunk / Engineering Dark Theme) ---
COLOR_BG = "#1a1a1a"          # Main window background (Deep Grey)
COLOR_FRAME = "#2b2b2b"       # Card/Widget background (Lighter Grey)
COLOR_TEXT_HEADER = "#3B8ED0" # Primary Accent Blue for Titles
COLOR_TEXT_NORMAL = "#FFFFFF" # Standard White text
COLOR_TEXT_DIM = "#A0A0A0"    # Dimmed text for secondary info
COLOR_GOOD = "#2CC985"        # Green (Healthy/Low Load)
COLOR_WARN = "#F2A33C"        # Orange (Warning/Medium Load)
COLOR_CRIT = "#E04F5F"        # Red (Critical/High Load)
COLOR_INFO = "#5DA5DA"        # Light Blue for Hardware Model Names

# ==========================================
# 🔧 ADVANCED SCRAPING ENGINE
# ==========================================

def run_powershell(cmd):
    """
    Executes a PowerShell command safely and returns the output string.
    Uses '-NoProfile' and '-ExecutionPolicy Bypass' to ensure it runs on strict systems.
    """
    try:
        full_cmd = f"powershell -NoProfile -ExecutionPolicy Bypass -Command \"{cmd}\""
        # Hides the console window pop-up
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        result = subprocess.run(
            full_cmd, 
            capture_output=True, 
            text=True, 
            shell=True, 
            startupinfo=startupinfo
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except: pass
    return None

def read_registry(path, key):
    """
    Reads a value directly from the Windows Registry.
    Why? Reading Registry 'HKLM' is often allowed for standard users,
    whereas WMI commands might throw 'Access Denied'.
    """
    try:
        # Open key with Read-Only permissions
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_READ) as reg_key:
            value, _ = winreg.QueryValueEx(reg_key, key)
            return str(value)
    except: pass
    return None

# ==========================================
# 🕵️ HARDWARE DETECTION LOGIC
# ==========================================

def get_cpu_brand():
    """
    Fetches the CPU Marketing Name.
    Tries Registry first (cleanest), falls back to platform (generic).
    """
    # Method 1: Registry (Best for Intel/AMD marketing names)
    name = read_registry(r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", "ProcessorNameString")
    if name: return name.strip()
    
    # Method 2: Standard Python Library
    return platform.processor()

def get_motherboard_info():
    """
    Fetches Motherboard Manufacturer and Product.
    This uses the Registry to bypass the need for Administrator privileges.
    """
    # Method 1: BIOS Information (Standard Desktops)
    manuf = read_registry(r"HARDWARE\DESCRIPTION\System\BIOS", "BaseBoardManufacturer")
    prod = read_registry(r"HARDWARE\DESCRIPTION\System\BIOS", "BaseBoardProduct")
    
    if manuf and prod and "System" not in manuf:
        return f"{manuf} {prod}".strip()
    
    # Method 2: System Information (Laptops/Pre-builts)
    sys_manuf = read_registry(r"HARDWARE\DESCRIPTION\System\BIOS", "SystemManufacturer")
    sys_prod = read_registry(r"HARDWARE\DESCRIPTION\System\BIOS", "SystemProductName")
    
    if sys_manuf and sys_prod:
        return f"{sys_manuf} {sys_prod}".strip()

    return "Generic Motherboard"

def format_marketing_size(bytes_size):
    """
    Smart Storage Calculation.
    Windows calculates in Binary (TiB - 1024 based).
    Manufacturers sell in Decimal (TB - 1000 based).
    
    This function detects large drives and shows BOTH values to avoid confusion.
    Example: A '4TB' drive shows as '3.63 TiB'. This function returns: "3.64 TiB (4.0 TB)"
    """
    if bytes_size == 0: return "0B"
    
    # Binary Math (What Windows sees)
    tib = bytes_size / (1024**4)
    # Decimal Math (What the Box says)
    tb = bytes_size / (1000**4)
    
    # If drive is 1 TB or larger, show dual format
    if tb > 0.9:
        marketing_str = f"{round(tb, 1)} TB"
    else:
        # Smaller drives (GB)
        gb = bytes_size / (1000**3)
        marketing_str = f"{round(gb, 0)} GB"

    return f"{tib:.2f} TiB ({marketing_str})"

def get_disk_physical_info():
    """
    Uses PowerShell to identify PHYSICAL Disks (Hardware), not just partitions.
    Parses CSV output for 100% reliability.
    """
    results = []
    ps_cmd = "Get-PhysicalDisk | Select-Object -Property FriendlyName,Size | ConvertTo-Csv -NoTypeInformation"
    val = run_powershell(ps_cmd)
    
    if val:
        lines = val.splitlines()
        # Skip the first line (Header)
        for line in lines[1:]:
            try:
                # CSV line format: "Samsung SSD...","500107862016"
                parts = line.split(',')
                if len(parts) >= 2:
                    # Clean quotes
                    name = parts[0].replace('"', '')
                    size_str = parts[1].replace('"', '')
                    
                    # Convert size to dual format
                    size_bytes = int(size_str)
                    size_fmt = format_marketing_size(size_bytes)
                    
                    results.append(f"• {name} [{size_fmt}]")
            except: pass
            
    return results if results else ["Generic Storage"]

def get_monitor_name():
    """
    Decodes the EDID (Extended Display Identification Data) from WMI 
    to find the real Monitor Model Name (e.g. "Dell U2415").
    """
    cmd = "Get-CimInstance WmiMonitorID -Namespace root\\wmi | ForEach-Object {($_.UserFriendlyName -ne 0 | ForEach-Object {[char]$_}) -join ''}"
    val = run_powershell(cmd)
    if val: return val.replace("\r", " + ").strip()
    
    # Fallback: Just show resolution
    return f"Generic Display ({ctk.CTk().winfo_screenwidth()}x{ctk.CTk().winfo_screenheight()})"

def get_cpu_temp():
    """
    The "Aggressive" Temperature Probe.
    Tries 4 different methods to find a valid temperature reading without asking for Admin.
    """
    # Method 1: Standard Linux/Cross-platform sensors
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            for name, entries in temps.items():
                if 'cpu' in name.lower(): return entries[0].current
    except: pass

    # Method 2: WMI Performance Counters (Often accessible by Users)
    # This reads the thermal zone info exposed to the OS performance monitor.
    try:
        cmd = "(Get-WmiObject Win32_PerfFormattedData_Counters_ThermalZoneInformation).Temperature"
        val = run_powershell(cmd)
        if val:
            # Usually returns Kelvin (e.g. 310 K)
            t = int(val)
            if t > 200: return t - 273.15
            if t > 0: return t
    except: pass

    # Method 3: WMI MSAcpi (Standard BIOS interface)
    try:
        cmd = "(Get-WmiObject MSAcpi_ThermalZoneTemperature -Namespace \"root/wmi\").CurrentTemperature"
        val = run_powershell(cmd)
        if val:
            # Returns deci-Kelvin
            return (int(val) / 10.0) - 273.15
    except: pass

    # Method 4: OpenHardwareMonitor Bridge
    # If the user has OHM running in background, we can read its data via WMI.
    try:
        cmd = "Get-WmiObject -Namespace root\\OpenHardwareMonitor -Class Sensor | Where-Object { $_.SensorType -eq 'Temperature' -and $_.Name -like '*CPU*' } | Select-Object -ExpandProperty Value"
        val = run_powershell(cmd)
        if val:
            return float(val)
    except: pass

    return None

# --- FORMATTING HELPERS ---

def get_ram_details():
    """
    Fetches RAM Stick details (Brand, Speed) using PowerShell CIM instances.
    """
    try:
        cmd = "Get-CimInstance Win32_PhysicalMemory | Select-Object Manufacturer,PartNumber,Speed | ConvertTo-Csv -NoTypeInformation"
        val = run_powershell(cmd)
        if val:
            lines = val.splitlines()
            if len(lines) > 1:
                p = lines[1].split(',')
                if len(p) >= 3:
                    man = p[0].replace('"','').strip()
                    part = p[1].replace('"','').strip()
                    spd = p[2].replace('"','').strip()
                    # Return Part Number if Manufacturer is generic code
                    if "0000" in man or len(man) < 2: return f"{part} @ {spd} MHz"
                    return f"{man} {part} @ {spd} MHz"
    except: pass
    return "Standard Memory"

def get_size(bytes, suffix="B"):
    """Formats bytes to KB, MB, GB for general usage."""
    factor = 1024
    for unit in ["", "K", "M", "G", "T", "P"]:
        if bytes < factor: return f"{bytes:.2f}{unit}{suffix}"
        bytes /= factor

def get_color_by_usage(percent):
    """Returns color hex code based on load intensity."""
    if percent < 50: return COLOR_GOOD
    if percent < 80: return COLOR_WARN
    return COLOR_CRIT

# ==========================================
# 🚀 MAIN APP CLASS
# ==========================================

class SystemMonitorApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # --- Window Initialization ---
        self.title(APP_TITLE)
        self.geometry(f"{APP_SIZE}+{WINDOW_X}+{WINDOW_Y}")
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")

        # --- Hardware Analysis (Run Once) ---
        self.hw_cpu_model = get_cpu_brand()
        self.hw_motherboard = get_motherboard_info() 
        self.hw_disk_physical = get_disk_physical_info() 
        self.hw_monitor_name = get_monitor_name()
        self.hw_ram_model = get_ram_details()
        
        # Performance Score: A fun metric based on cores and RAM
        self.perf_rating = min(100, (psutil.cpu_count() * 5) + (psutil.virtual_memory().total // (1024**3)))
        
        # Tracking Variables
        self.old_net_io = psutil.net_io_counters()
        self.ping_latency = 0 
        
        # --- UI Layout Setup ---
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Build Header
        self.create_header_section()
        
        # Build Scrollable Body
        self.scroll_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=10, pady=10)
        self.scroll_frame.grid_columnconfigure(0, weight=1)
        self.scroll_frame.grid_columnconfigure(1, weight=1)

        # Build Content Sections
        self.create_cpu_section()
        self.create_memory_section()
        self.create_storage_section()
        self.create_network_section()

        # --- Start Loops ---
        self.start_ping_thread() # Background Network Check
        self.update_ui_loop()    # Main GUI Update Timer

    # ---------------------------------------------------------
    # UI CONSTRUCTION METHODS
    # ---------------------------------------------------------

    def create_header_section(self):
        self.header_frame = ctk.CTkFrame(self, corner_radius=15, fg_color=COLOR_FRAME)
        self.header_frame.grid(row=0, column=0, columnspan=2, padx=15, pady=(15, 5), sticky="ew")
        
        # Top Line: Title + Hostname
        title_text = f"💻 {APP_TITLE}  |  Host: {platform.node()}"
        self.lbl_title = ctk.CTkLabel(self.header_frame, text=title_text, font=("Roboto", 22, "bold"), text_color=COLOR_TEXT_HEADER)
        self.lbl_title.pack(pady=(10, 0))
        
        # Hardware Line: Motherboard + Monitor
        self.lbl_mobo = ctk.CTkLabel(self.header_frame, text=f"Motherboard: {self.hw_motherboard}  |  Display: {self.hw_monitor_name}", font=("Arial", 12, "bold"), text_color=COLOR_INFO)
        self.lbl_mobo.pack(pady=(5, 0))

        # Status Line: Health + Uptime
        self.lbl_health = ctk.CTkLabel(self.header_frame, text="System Health: 100% (Excellent)", font=("Arial", 14, "bold"), text_color=COLOR_GOOD)
        self.lbl_health.pack(pady=(5, 0))
        self.lbl_uptime = ctk.CTkLabel(self.header_frame, text="Uptime: ...", font=("Consolas", 12), text_color=COLOR_TEXT_DIM)
        self.lbl_uptime.pack(pady=(0, 10))

    def create_cpu_section(self):
        self.cpu_frame = ctk.CTkFrame(self.scroll_frame, corner_radius=10, fg_color=COLOR_FRAME)
        self.cpu_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        
        # Header Info
        ctk.CTkLabel(self.cpu_frame, text="CPU INFORMATION", font=("Arial", 16, "bold"), text_color=COLOR_TEXT_HEADER).pack(pady=(10,0))
        ctk.CTkLabel(self.cpu_frame, text=self.hw_cpu_model, font=("Arial", 11, "bold"), text_color=COLOR_INFO).pack(pady=(0,10))
        
        # Main Usage Bar
        stats = ctk.CTkFrame(self.cpu_frame, fg_color="transparent")
        stats.pack(fill="x", padx=15)
        self.lbl_cpu_val = ctk.CTkLabel(stats, text="Load: 0%", font=("Arial", 12, "bold"))
        self.lbl_cpu_val.pack(side="left")
        self.lbl_cpu_temp = ctk.CTkLabel(stats, text="Temperature: N/A", font=("Arial", 12, "bold"), text_color=COLOR_WARN)
        self.lbl_cpu_temp.pack(side="right")

        self.prog_cpu = ctk.CTkProgressBar(self.cpu_frame, height=15)
        self.prog_cpu.pack(fill="x", padx=15, pady=5)
        self.lbl_cpu_freq = ctk.CTkLabel(self.cpu_frame, text="Clock: 0 MHz", text_color=COLOR_TEXT_DIM)
        self.lbl_cpu_freq.pack(anchor="w", padx=15)

        # Core Grid
        ctk.CTkLabel(self.cpu_frame, text=f"Logical Cores ({psutil.cpu_count()})", font=("Arial", 12, "bold")).pack(pady=(15, 5))
        self.cores_frame = ctk.CTkFrame(self.cpu_frame, fg_color="transparent")
        self.cores_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        self.core_widgets = []
        for i in range(min(psutil.cpu_count(), 32)):
            f = ctk.CTkFrame(self.cores_frame, fg_color="transparent")
            f.grid(row=i//4, column=i%4, padx=5, pady=2, sticky="ew")
            lbl = ctk.CTkLabel(f, text=f"Core {i+1}", font=("Consolas", 10), width=60, anchor="w")
            lbl.pack(side="left")
            bar = ctk.CTkProgressBar(f, height=6, width=50)
            bar.pack(side="left", padx=5)
            self.core_widgets.append((lbl, bar))

    def create_memory_section(self):
        self.mem_frame = ctk.CTkFrame(self.scroll_frame, corner_radius=10, fg_color=COLOR_FRAME)
        self.mem_frame.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        
        ctk.CTkLabel(self.mem_frame, text="MEMORY", font=("Arial", 16, "bold"), text_color=COLOR_TEXT_HEADER).pack(pady=(10,0))
        ctk.CTkLabel(self.mem_frame, text=self.hw_ram_model, font=("Arial", 11), text_color=COLOR_INFO).pack(pady=(0,10))
        
        # Physical RAM
        self.lbl_ram_title = ctk.CTkLabel(self.mem_frame, text="Physical RAM", font=("Arial", 13, "bold"))
        self.lbl_ram_title.pack(anchor="w", padx=15)
        self.lbl_ram_text = ctk.CTkLabel(self.mem_frame, text="...", font=("Consolas", 11))
        self.lbl_ram_text.pack(anchor="w", padx=15)
        self.prog_ram = ctk.CTkProgressBar(self.mem_frame, height=15)
        self.prog_ram.pack(fill="x", padx=15, pady=5)
        
        ctk.CTkLabel(self.mem_frame, text="").pack(pady=2)

        # Virtual Memory
        self.lbl_swap_title = ctk.CTkLabel(self.mem_frame, text="Virtual Memory (Swap)", font=("Arial", 13, "bold"), text_color=COLOR_TEXT_HEADER)
        self.lbl_swap_title.pack(anchor="w", padx=15)
        self.lbl_swap_text = ctk.CTkLabel(self.mem_frame, text="...", font=("Consolas", 11))
        self.lbl_swap_text.pack(anchor="w", padx=15)
        self.prog_swap = ctk.CTkProgressBar(self.mem_frame, height=15)
        self.prog_swap.pack(fill="x", padx=15, pady=5)

    def create_storage_section(self):
        self.disk_frame = ctk.CTkFrame(self.scroll_frame, corner_radius=10, fg_color=COLOR_FRAME)
        self.disk_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        
        ctk.CTkLabel(self.disk_frame, text="STORAGE DEVICES", font=("Arial", 16, "bold"), text_color=COLOR_TEXT_HEADER).pack(pady=(10,0))
        
        # Show Physical Hardware Info
        if self.hw_disk_physical:
            phys_text = "\n".join(self.hw_disk_physical)
            ctk.CTkLabel(self.disk_frame, text=phys_text, font=("Consolas", 11, "bold"), text_color=COLOR_INFO, justify="left").pack(pady=(0, 10))
        
        # Logical Partitions
        self.drives_container = ctk.CTkFrame(self.disk_frame, fg_color="transparent")
        self.drives_container.pack(fill="both", expand=True, padx=10, pady=5)
        self.drive_widgets = {} 

    def create_network_section(self):
        self.net_frame = ctk.CTkFrame(self.scroll_frame, corner_radius=10, fg_color=COLOR_FRAME)
        self.net_frame.grid(row=1, column=1, padx=10, pady=10, sticky="nsew")
        
        ctk.CTkLabel(self.net_frame, text="NETWORK & HEALTH", font=("Arial", 16, "bold"), text_color=COLOR_TEXT_HEADER).pack(pady=10)
        
        self.lbl_ping = ctk.CTkLabel(self.net_frame, text="Ping: -- ms", font=("Consolas", 16, "bold"))
        self.lbl_ping.pack(pady=5)
        
        self.net_grid = ctk.CTkFrame(self.net_frame, fg_color="transparent")
        self.net_grid.pack(fill="x", padx=20)
        
        self.lbl_down_val = ctk.CTkLabel(self.net_grid, text="0.00 KB/s", font=("Consolas", 20, "bold"), text_color=COLOR_GOOD)
        self.lbl_down_val.grid(row=0, column=0, padx=20)
        ctk.CTkLabel(self.net_grid, text="⬇ DOWNLOAD", font=("Arial", 10)).grid(row=1, column=0)
        
        self.lbl_up_val = ctk.CTkLabel(self.net_grid, text="0.00 KB/s", font=("Consolas", 20, "bold"), text_color=COLOR_WARN)
        self.lbl_up_val.grid(row=0, column=1, padx=20)
        ctk.CTkLabel(self.net_grid, text="⬆ UPLOAD", font=("Arial", 10)).grid(row=1, column=1)

        ctk.CTkLabel(self.net_frame, text="HARDWARE RATING", font=("Arial", 12, "bold"), text_color=COLOR_TEXT_DIM).pack(pady=(20, 5))
        self.prog_rating = ctk.CTkProgressBar(self.net_frame, height=10, progress_color=COLOR_INFO)
        self.prog_rating.set(self.perf_rating / 100)
        self.prog_rating.pack(fill="x", padx=40)
        ctk.CTkLabel(self.net_frame, text=f"Score: {self.perf_rating}/100", font=("Arial", 10)).pack()

    # ---------------------------------------------------------
    # DATA REFRESH LOOPS
    # ---------------------------------------------------------

    def get_system_uptime(self):
        boot = datetime.fromtimestamp(psutil.boot_time())
        return str(datetime.now() - boot).split('.')[0]

    def start_ping_thread(self):
        def check_ping_logic():
            while True:
                try:
                    st = time.time()
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(1.0)
                    s.connect(("8.8.8.8", 53))
                    s.close()
                    self.ping_latency = (time.time() - st) * 1000
                except: self.ping_latency = -1
                time.sleep(1)
        thread = threading.Thread(target=check_ping_logic, daemon=True)
        thread.start()

    def calculate_health(self, cpu, ram):
        load = 100 - ((cpu + ram) / 2)
        if self.ping_latency == -1: load -= 20
        return max(0, min(100, int(load)))

    def update_ui_loop(self):
        # 1. CPU Updates
        cpu_pct = psutil.cpu_percent()
        cpu_free = 100 - cpu_pct
        self.lbl_cpu_val.configure(text=f"Used: {cpu_pct}% | Free: {100-cpu_pct:.1f}%")
        self.lbl_cpu_freq.configure(text=f"Clock: {psutil.cpu_freq().current:.0f} MHz")
        self.prog_cpu.set(cpu_pct / 100)
        self.prog_cpu.configure(progress_color=get_color_by_usage(cpu_pct))
        
        # Temp Update (Aggressive Check)
        temp = get_cpu_temp()
        if temp:
            self.lbl_cpu_temp.configure(text=f"Temperature: {temp:.1f}°C")
        else:
            self.lbl_cpu_temp.configure(text=f"Temperature: N/A (Sensor Locked)")

        # Core Updates
        cores = psutil.cpu_percent(percpu=True)
        for i, usage in enumerate(cores):
            if i < len(self.core_widgets):
                lbl, bar = self.core_widgets[i]
                lbl.configure(text=f"Core {i+1}: {usage:.0f}%") 
                bar.set(usage / 100)
                bar.configure(progress_color=get_color_by_usage(usage))

        # 2. Memory Updates
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        self.lbl_ram_text.configure(text=f"RAM: Total: {get_size(mem.total)} | Used: {get_size(mem.used)} ({mem.percent}%)")
        self.prog_ram.set(mem.percent / 100)
        self.prog_ram.configure(progress_color=get_color_by_usage(mem.percent))
        self.lbl_swap_text.configure(text=f"SWAP: Total: {get_size(swap.total)} | Used: {get_size(swap.used)} ({swap.percent}%)")
        self.prog_swap.set(swap.percent / 100)
        self.prog_swap.configure(progress_color=get_color_by_usage(swap.percent))

        # 3. Storage Updates (Partitions)
        partitions = psutil.disk_partitions()
        for p in partitions:
            try:
                if 'cdrom' in p.opts or p.fstype == '': continue
                usage = psutil.disk_usage(p.mountpoint)
                drive_name = p.device
                
                if drive_name not in self.drive_widgets:
                    f = ctk.CTkFrame(self.drives_container, fg_color="transparent")
                    f.pack(fill="x", pady=5)
                    lbl_name = ctk.CTkLabel(f, text=drive_name, width=50, anchor="w", font=("Arial", 12, "bold"))
                    lbl_name.pack(side="left")
                    bar = ctk.CTkProgressBar(f)
                    bar.pack(side="left", fill="x", expand=True, padx=10)
                    lbl_det = ctk.CTkLabel(f, text="", font=("Consolas", 11), width=220, anchor="e")
                    lbl_det.pack(side="right")
                    self.drive_widgets[drive_name] = (bar, lbl_det)
                
                bar, lbl_det = self.drive_widgets[drive_name]
                bar.set(usage.percent / 100)
                bar.configure(progress_color=get_color_by_usage(usage.percent))
                lbl_det.configure(text=f"{usage.percent}% ({get_size(usage.used)} / {get_size(usage.total)})")
            except: continue

        # 4. Network Updates
        new_net = psutil.net_io_counters()
        ds = new_net.bytes_recv - self.old_net_io.bytes_recv
        us = new_net.bytes_sent - self.old_net_io.bytes_sent
        self.old_net_io = new_net
        self.lbl_down_val.configure(text=f"{get_size(ds)}/s")
        self.lbl_up_val.configure(text=f"{get_size(us)}/s")

        if self.ping_latency == -1:
            self.lbl_ping.configure(text="Ping: Offline ❌", text_color=COLOR_CRIT)
        else:
            p_color = COLOR_GOOD if self.ping_latency < 100 else COLOR_WARN
            self.lbl_ping.configure(text=f"Ping (Google): {self.ping_latency:.0f} ms", text_color=p_color)

        self.lbl_health.configure(text=f"System Health: {self.calculate_health(cpu_pct, mem.percent)}%", text_color=COLOR_GOOD)
        self.lbl_uptime.configure(text=f"Uptime: {self.get_system_uptime()}")

        self.after(REFRESH_RATE, self.update_ui_loop)

if __name__ == "__main__":
    app = SystemMonitorApp()
    app.mainloop()