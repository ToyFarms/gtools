#version 450 core

layout (location = 0) in vec2 in_pos;
layout (location = 1) in vec4 in_color;

layout (location = 2) in vec3 in_tilePos;

uniform mat4 u_view_proj;
uniform mat4 u_model;
uniform float u_z;
uniform float u_layer_spread;

out vec4 color;

void main() {
    vec2 pos = in_pos + in_tilePos.xy;
    vec4 worldPos = u_model * vec4(pos, in_tilePos.z, 1.0);
    float z = u_z * u_layer_spread;
    gl_Position = u_view_proj * vec4(worldPos.xy, z, 1.0);
    color = in_color;
}
