#version 450 core
layout (location = 0) in vec2 a_pos;
layout (location = 1) in vec2 a_tex;
layout (location = 2) in vec2 a_offset;
layout (location = 3) in vec2 a_size;
layout (location = 4) in vec2 a_texOffset;
layout (location = 5) in vec2 a_texSize;
layout (location = 6) in float a_z;

uniform mat4 u_mvp;
uniform vec2 u_offset;

out vec2 v_tex;

void main() {
    v_tex = a_texOffset + a_tex * a_texSize;
    vec2 pos = a_offset + (a_pos + vec2(0.5)) * a_size + u_offset;
    gl_Position = u_mvp * vec4(pos, a_z, 1.0);
}
