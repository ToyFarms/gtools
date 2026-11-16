#version 450 core

out vec4 out_fragColor;

in vec2 v_uv;
in float v_alpha;

uniform sampler2DArray u_texture;
uniform float u_texLayer;

void main() {
    // npc1.rttex is a pixel-art sheet: snap to texel centres (NEAREST sampler)
    vec2 texSize = textureSize(u_texture, 0).xy;
    vec2 uv = (floor(v_uv * texSize) + 0.5) / texSize;

    vec4 color = texture(u_texture, vec3(uv, u_texLayer));
    color.a *= v_alpha;
    if (color.a < 0.001) {
        discard;
    }

    // the GUI blends premultiplied (GL_ONE, GL_ONE_MINUS_SRC_ALPHA)
    out_fragColor = vec4(color.rgb * color.a, color.a);
}
