#version 450 core

out vec4 out_fragColor;
in vec4 color;

void main() {
    out_fragColor = vec4(color.rgb * color.a, color.a);
}
