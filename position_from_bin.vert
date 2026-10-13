#version 400 core

// Don't use input attributes, only gl_VertexID
// layout (location = 0) in float dummy; // Can be removed entirely

// Texture with bin indices (from Pass 1)
uniform usampler2D binTexture; // usampler for reading uint texture
uniform ivec2 inputTextureSize; // Size of original volumeTexture

const int HISTOGRAM_SIZE = 256;

void main()
{
    // Calculate 2D pixel coordinates in original texture by vertex ID
    int pixelIndex = gl_VertexID;
    ivec2 texCoordInt = ivec2(pixelIndex % inputTextureSize.x, pixelIndex / inputTextureSize.x);

    // Read bin index for this pixel from binTexture
    uint bin_index = texelFetch(binTexture, texCoordInt, 0).r; // Level 0

    // Convert bin index to normalized X-coordinate [0, 1]
    // Add 0.5 for centering in histogram pixel
    float normX = (float(bin_index) + 0.5) / float(HISTOGRAM_SIZE);

    // Convert normalized coordinate to Clip Space [-1, 1]
    float clipX = normX * 2.0 - 1.0;

    // Output point to center of corresponding histogram pixel
    // Y and Z don't matter for 1D histogram in 2D texture
    gl_Position = vec4(clipX, 0.0, 0.0, 1.0);

    // Set point size (if rendering as points)
    gl_PointSize = 1.0; // Not necessary if fragment shader just writes 1
}