import scriptcontext as sc


# Get the current Rhino document and it's layers
doc = sc.doc
layers = doc.Layers

def toggle_all_layers_expansion():
    
    is_expanded = 0

    for layer in layers:
        if layer.IsExpanded:
            is_expanded += 1
    
    if is_expanded > 0:
        set_all_layers_expanded(False)
    else:
        set_all_layers_expanded(True)

def set_all_layers_expanded(expand):

    for layer in layers:

        if layer.IsExpanded == expand: #Skip layers that are already expanded or collapsed
            continue

        layer.IsExpanded = expand

        # Commit the changed layer back into the document's layer table.
        #
        # Arguments:
        #   layer             = the modified layer object
        #   layer.LayerIndex  = where this layer lives in the layer table
        #   True              = quiet; do not show user interface warnings
        doc.Layers.Modify(layer, layer.LayerIndex, True)

    # Ask Rhino to refresh its views/interface.
    doc.Views.Redraw()

toggle_all_layers_expansion()