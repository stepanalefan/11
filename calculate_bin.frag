#version 400 core

in vec2 TexCoord;
// Integer output format required
layout (location = 0) out uvec4 FragColor; // uint output

uniform sampler2D inputTexture; // R32f
uniform float maxVolume;

const int HISTOGRAM_SIZE = 256; // Must match C# and other shaders

void main()
{
    float volume = abs(texture(inputTexture, TexCoord).r);
    float normalized_volume = clamp(volume / maxVolume, 0.0, 1.0);
    uint bin_index = uint(floor(normalized_volume * float(HISTOGRAM_SIZE - 1)));

    // Write bin index to single output channel (red)
    FragColor = uvec4(bin_index, 0, 0, 1);
}