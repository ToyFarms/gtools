#version 450 core
layout (location = 0) in vec2 in_pos;
layout (location = 1) in vec2 in_tex;
layout (location = 2) in vec2 in_offset;
layout (location = 3) in vec2 in_size;
layout (location = 4) in vec2 in_texOffset;
layout (location = 5) in vec2 in_texSize;
layout (location = 6) in float in_z;
layout (location = 7) in vec3 in_color;

uniform mat4 u_mvp;
uniform vec2 u_offset;

out vec2 v_tex;
out vec3 v_color;

void main() {
    v_tex = in_texOffset + in_tex * in_texSize;
    v_color = in_color;
    vec2 pos = in_offset + (in_pos + vec2(0.5)) * in_size + u_offset;
    gl_Position = u_mvp * vec4(pos, in_z, 1.0);
}
