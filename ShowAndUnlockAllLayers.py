#Rune Wriedt, 2026-06-18

import rhinoscriptsyntax as rs

def show_and_unlock_all_layers():
    
    layers = rs.LayerNames()

    if not layers:
        return

    for name in layers:
        try:
            rs.LayerVisible(name, True, True)
            
            rs.LayerLocked(name, False)

        except Exception:
            print("Could not update layer:", name, Exception)

show_and_unlock_all_layers()