import scriptcontext as sc


# Get the current Rhino document
doc = sc.doc

layers = []

def toggle_all_layers_expansion():
    
    for layer in doc.Layers:

        #It's important to skip the deleted layers that Rhino might be caching,
        #as the script might not work otherwise
        if layer.IsDeleted:     
            continue

        layers.append(layer)
    
    if not layers:
        print("No layers found")
        return

    is_expanded = 0

    for layer in layers:
        if layer.IsExpanded:
            is_expanded += 1
    
    if is_expanded > 0:
        set_all_layers_expanded(layers, False)
    else:
        set_all_layers_expanded(layers, True)

def set_all_layers_expanded(layers, expand):

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