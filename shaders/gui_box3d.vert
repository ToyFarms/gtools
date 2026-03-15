#version 450 core
layout (location = 0) in vec2 in_pos;
layout (location = 1) in vec2 in_texCoord;

uniform mat4 u_view_proj;
uniform mat4 u_model;
uniform float u_z;
uniform float u_layer_spread;

out vec2 texCoord;

void main() {
    vec4 worldPos = u_model * vec4(in_pos, 0.0, 1.0);
    gl_Position = u_view_proj * vec4(worldPos.xy, u_z * u_layer_spread, 1.0);
    texCoord = in_texCoord;
}
