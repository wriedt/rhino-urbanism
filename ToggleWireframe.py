#Rune Wriedt, 2026-06-18
import Rhino.Display as rd
import scriptcontext

#Key is used to store the previous display mode during the current session
#It is used to look up a value in a dictionary in scriptcontext.sticky
sticky_key = "toggle_wireframe_display_mode_id" 

wireframe_mode_id = rd.DisplayModeDescription.WireframeId
wireframe_mode = rd.DisplayModeDescription.GetDisplayMode(wireframe_mode_id)
shaded_mode_id = rd.DisplayModeDescription.ShadedId
shaded_mode = rd.DisplayModeDescription.GetDisplayMode(shaded_mode_id)

#Main function
def toggle_wireframe():

    active_view = scriptcontext.doc.Views.ActiveView
    if active_view is None:
        print("There is no active view")
        return

    viewport = active_view.ActiveViewport

    current_display_mode = viewport.DisplayMode
    current_display_mode_id = current_display_mode.Id


    if current_display_mode_id != wireframe_mode_id:
        print("Display mode changed to Wireframe")
        scriptcontext.sticky[sticky_key] = current_display_mode_id  #The id of the display mode is stored in the sticky dictionary
        viewport.DisplayMode = wireframe_mode

    else:
        if sticky_key in scriptcontext.sticky:
            previous_mode_id = scriptcontext.sticky[sticky_key]
            previous_mode = viewport.DisplayMode = rd.DisplayModeDescription.GetDisplayMode(previous_mode_id)

            if previous_mode_id is not None:
                print("Display mode changed to previous mode")
                viewport.DisplayMode = previous_mode
            else:
                print("Previous mode could not be found. Display mode changed to Shaded")
                viewport.DisplayMode = shaded_mode

        else:
            print("Previous mode could not be found. Display mode changed to Shaded")
            viewport.DisplayMode = shaded_mode

    active_view.Redraw()

toggle_wireframe()