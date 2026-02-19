#version 450 core

layout (location = 0) in vec2 in_pos;
layout (location = 1) in vec2 in_texCoord;
layout (location = 2) in float in_layer;

out vec2 texCoord;
flat out float layer;

uniform mat4 u_mvp;

void main() {
    gl_Position = u_mvp * vec4(in_pos, 0.0, 1.0);
    texCoord = in_texCoord;
    layer = in_layer;
}
