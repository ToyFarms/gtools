#version 450 core

out vec4 out_fragColor;
in vec2 texCoord;
flat in float layer;
uniform sampler2DArray texArray;

void main() {
    out_fragColor = texture(texArray, vec3(texCoord, layer));
}
