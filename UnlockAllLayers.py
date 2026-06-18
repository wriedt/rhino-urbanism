#Rune Wriedt, 2026-06-18

import rhinoscriptsyntax as rs

def unlock_all_layers():
    
    layers = rs.LayerNames()

    if not layers:
        return

    for name in layers:
        try:
            rs.LayerLocked(name, False)

        except Exception as e:
            print("Could not unlock layer '{}': {}".format(name, e))

unlock_all_layers()