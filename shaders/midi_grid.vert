#version 450 core

layout (location = 0) in vec2 in_pos;
uniform mat4 u_proj;
uniform vec2 u_min;
uniform vec2 u_max;

out vec2 v_worldPos;

void main() {
    vec2 worldPos = mix(u_min, u_max, in_pos);
    gl_Position = u_proj * vec4(worldPos, 0.0, 1.0);
    v_worldPos = worldPos;
}
