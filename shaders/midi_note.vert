#version 450 core

layout (location = 0) in vec2 in_pos;
layout (location = 1) in vec2 in_uv;

layout (location = 2) in vec2 in_rectPos;
layout (location = 3) in vec2 in_rectSize;
layout (location = 4) in vec4 in_color;

uniform mat4 u_proj;

out vec4 color;
out vec2 uv;

void main() {
    vec2 pos = (in_pos + 0.5) * in_rectSize + in_rectPos;
    gl_Position = u_proj * vec4(pos, 0.0, 1.0);
    color = in_color;
    uv = in_uv;
}
