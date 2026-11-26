"""Demo: hold CTRL (and keep still for a moment) to open the pie menu.

    pip install imgui-bundle glfw PyOpenGL
    python demo.py

Try: flick toward an option and release CTRL. Push outward on "Tools" to dive into
its nested pie; move back toward the faint parent to return. "Search" turns into a
text field with live results in a floating panel.
"""
import ctypes

import glfw
from imgui_bundle import imgui
from OpenGL import GL as gl

from gtools.gui.lib.pie import Hold, Panel, PieMenu

WORDS = ["apple", "apricot", "avocado", "banana", "blueberry", "cherry", "coconut",
         "grape", "kiwi", "lemon", "lime", "mango", "orange", "papaya", "peach",
         "pear", "pineapple", "plum", "raspberry", "strawberry", "watermelon"]


def main():
    assert glfw.init()
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, True)
    win = glfw.create_window(1000, 640, "PieMenu demo", None, None)
    glfw.make_context_current(win)
    glfw.swap_interval(1)

    imgui.create_context()
    imgui.backends.glfw_init_for_opengl(ctypes.cast(win, ctypes.c_void_p).value, True)
    imgui.backends.opengl3_init("#version 330")

    # --- the pie menu: global trigger. Use processes=["myapp.exe", "blender.exe"]
    # --- to only react while one of those is the foreground application.
    menu = PieMenu(trigger=Hold("ctrl", delay=0), processes=None)

    menu.button("Copy", lambda: print("copy"), icon="C")
    menu.button("Paste", lambda: print("paste"), icon="P")

    @menu.button("Undo")
    def undo():
        print("undo")

    tools = menu.submenu("Tools")
    tools.button("Screenshot", lambda: print("screenshot"))
    tools.button("Color picker", lambda: print("picker"))
    layout = tools.submenu("Layout")                     # pie within pie within pie
    for name in ("Left", "Right", "Top", "Bottom"):
        layout.button(name, lambda n=name: print("dock", n))
    tools.button("Reset", lambda: print("reset"), color=(255, 110, 110, 255))

    # Live search: TextInput + a results Panel that updates as you type.
    search = {"q": "", "panel": None}

    def on_change(text):
        search["q"] = text
        panel = search["panel"]
        if text and (panel is None or not panel.open):
            search["panel"] = menu.show_panel(Panel.list(
                "Search results",
                lambda: [w for w in WORDS if search["q"].lower() in w][:14],
                on_pick=lambda w: print("picked", w), size=(300, 320)))
        elif not text and panel is not None:
            panel.close()

    menu.text_input("Search", on_submit=lambda t: print("submitted:", t),
                    on_change=on_change, placeholder="Search fruit...")

    menu.panel("Info", lambda: Panel(
        "Info", lambda p: (imgui.text("Any ImGui widgets here."),
                           imgui.text(f"Frame: {imgui.get_frame_count()}")), size=(260, 120)))

    while not glfw.window_should_close(win):
        glfw.poll_events()
        w, h = glfw.get_framebuffer_size(win)
        gl.glViewport(0, 0, w, h)
        gl.glClearColor(0.10, 0.11, 0.14, 1.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)

        imgui.backends.opengl3_new_frame()
        imgui.backends.glfw_new_frame()
        imgui.new_frame()
        imgui.set_next_window_pos(imgui.ImVec2(30, 30), imgui.Cond_.once.value)
        imgui.begin("Main app")
        imgui.text("Hold CTRL to open the pie menu.")
        imgui.end()
        imgui.render()
        imgui.backends.opengl3_render_draw_data(imgui.get_draw_data())
        glfw.swap_buffers(win)

        menu.update()   # one call per frame; leaves your GL / ImGui contexts untouched

    menu.destroy()
    glfw.terminate()


if __name__ == "__main__":
    main()

