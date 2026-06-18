# Rune Wriedt 2026-06-18

import rhinoscriptsyntax as rs


def isolate_layer():
    print("test")

# Prompt user to select one or more objects or input the object(s) already selected

# Show a toggle in command line to include potential children in isolation

# Get the layer from the object

# If layer is a sublayer, get the parent layers

# If layer has children, get the children

# Store current visibility state of all layers, so that the isolation can be undone by UnisolateLayer.py

# Turn off all layers that are not the layer(s) of the selected object(s) and the parents, potentially children too


isolate_layer()