#version 450 core

out vec4 out_fragColor;

in vec2 v_uv;

uniform sampler2DArray u_texture;
uniform float u_texLayer;

void main() {
    // particle sheets are pixel art: snap to texel centres (NEAREST sampler)
    vec2 texSize = textureSize(u_texture, 0).xy;
    vec2 uv = (floor(v_uv * texSize) + 0.5) / texSize;

    vec4 color = texture(u_texture, vec3(uv, u_texLayer));
    if (color.a < 0.001) {
        discard;
    }

    // the GUI blends premultiplied (GL_ONE, GL_ONE_MINUS_SRC_ALPHA)
    out_fragColor = vec4(color.rgb * color.a, color.a);
}
