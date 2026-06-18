#Rune Wriedt, 2026-06-18

import rhinoscriptsyntax as rs

def show_all_layers():
    
    layers = rs.LayerNames()

    rs.EnableRedraw(False)

    if not layers:
        return

    for name in layers:
        try:
            rs.LayerVisible(name, True)

        except Exception as e:
            print("Could not show layer '{}': {}".format(name, e))

        finally:
            rs.EnableRedraw(True)


show_all_layers()