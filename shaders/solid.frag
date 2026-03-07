#version 450 core

out vec4 out_fragColor;
in vec3 color;

void main() {
    out_fragColor = vec4(color, 1.0);
}
