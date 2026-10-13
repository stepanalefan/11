#version 400 core

in vec2 TexCoord;

out vec4 FragColor;

uniform sampler2D sliceTexture;
uniform int startX;

void main()
{
    if (gl_FragCoord.x >= startX)
    {
        float value = texture(sliceTexture, TexCoord).r;
        FragColor = vec4(value, 0.0, 0.0, 1.0);
    }
    else
    {
        discard;
    }
}