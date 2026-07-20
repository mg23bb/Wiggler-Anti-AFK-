# Wiggler — Anti-AFK Mouse Mover

A lightweight, zero-dependency Windows utility written in Python that simulates mouse movement to prevent system idle states, instantly updating `GetLastInputInfo` and OS idle timers.

Unlike naive automation tools that teleport the cursor or snap it erratically across the screen, **Wiggler** generates smooth, mathematically calculated, relative vector paths that seamlessly return the cursor to its exact starting pixel after every cycle.

---

## 🛡️ Why It Bypasses Anti-Cheat

If you are using this to prevent being kicked from a game or workspace, staying undetected is critical. Wiggler bypasses typical telemetry flagging through several design features built directly into the codebase:

> [!TIP]
> **Why it works:** Wiggler never touches, reads, or hooks into the memory of other running applications or games. It operates purely on the Windows desktop level, avoiding the heuristic flags triggered by software that scans or injects into game clients.

* **Kernel/OS Legitimacy (`SendInput`)**
Many simple scripts use high-level methods like `SetCursorPos`, which completely bypasses the OS input queue. Wiggler uses the Win32 `SendInput` API with the `INPUT_MOUSE` type. To Windows (and any listening process), this is structurally identical to a hardware device driver generating relative movement packet flags (`MOUSEEVENTF_MOVE`).


* **Randomized Path Trajectories**
The execution path calculates a fresh, arbitrary angle (`random.uniform(0, 2 * math.pi)`) every single time a wiggle occurs. Because the angle is completely random, it lacks a predictable algorithmic signature.


* **Zero Third-Party Dependencies**
Cheat detectors scan process trees for known automation libraries like PyAutoGUI or AutoIt. Wiggler avoids this entirely by calling native Windows system `dll` APIs using Python's built-in `ctypes` library.



---

## ⚙️ Features

| Feature | Description |
| --- | --- |
| **Granular Control** | Fine-tune wiggle distance (px), interval timers (seconds), and movement animation duration (ms) via simple sliders.

 |
| **Automatic Stop Triggers** | Set Wiggler to automatically stop after a specific duration.

 |
| **Post-Timer Actions** | Trigger native chain actions on expiry: Sleep PC, Close Wiggler, Force-kill a target client (`taskkill`), or run a custom command.

 |
| **System Tray Integration** | Minimize to the Windows system tray to keep your taskbar completely clear.

 |
| **Modern Dark UI** | Implements a clean dark theme utilizing a forced Windows DWM title bar color override for native Windows 10/11 aesthetic integration.

 |

---

## 🚀 Getting Started

### Prerequisites

* Windows 10 or 11
* Python 3.10+ (**No external `pip` packages required!**)



### Running the Script

Simply clone the repository and run the script:

```bash
# Clone the repository
git clone https://github.com/yourusername/Wiggler.git

# Navigate into the directory
cd Wiggler

# Run the utility
python wiggler.py

```

> [!NOTE]
> The script automatically detaches from the command line console on launch (`FreeConsole`) to keep your terminal free and workspace clean.
> 
>
