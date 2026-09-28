//! GPU conversion of captured BGRA frames into scaled NV12 textures for the H.264 encoder,
//! using the D3D11 video processor (no CPU copies).

use crate::context::Context;
use crate::device::GpuDevice;
use crate::geometry::Size;
use std::mem::ManuallyDrop;
use windows::Win32::Foundation::{E_FAIL, E_POINTER, RECT};
use windows::Win32::Graphics::Direct3D11::{
    D3D11_BIND_RENDER_TARGET, D3D11_TEX2D_VPIV, D3D11_TEX2D_VPOV, D3D11_TEXTURE2D_DESC,
    D3D11_USAGE_DEFAULT, D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE, D3D11_VIDEO_PROCESSOR_CONTENT_DESC,
    D3D11_VIDEO_PROCESSOR_FORMAT_SUPPORT_INPUT, D3D11_VIDEO_PROCESSOR_FORMAT_SUPPORT_OUTPUT,
    D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC, D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC_0,
    D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC, D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC_0,
    D3D11_VIDEO_PROCESSOR_STREAM, D3D11_VIDEO_USAGE_OPTIMAL_SPEED, D3D11_VPIV_DIMENSION_TEXTURE2D,
    D3D11_VPOV_DIMENSION_TEXTURE2D, ID3D11Texture2D, ID3D11VideoContext1, ID3D11VideoDevice,
    ID3D11VideoProcessor, ID3D11VideoProcessorEnumerator, ID3D11VideoProcessorOutputView,
};
use windows::Win32::Graphics::Dxgi::Common::{
    DXGI_COLOR_SPACE_RGB_FULL_G22_NONE_P709, DXGI_COLOR_SPACE_YCBCR_STUDIO_G22_LEFT_P709,
    DXGI_FORMAT_B8G8R8A8_UNORM, DXGI_FORMAT_NV12, DXGI_RATIONAL, DXGI_SAMPLE_DESC,
};
use windows_core::{BOOL, Error, Interface, Result};

/// Converts BGRA frames of one size into NV12 frames of another, writing into a small
/// ring of output textures so the encoder can still be reading earlier ones.
pub struct Nv12Converter {
    video_device: ID3D11VideoDevice,
    video_context: ID3D11VideoContext1,
    enumerator: ID3D11VideoProcessorEnumerator,
    processor: ID3D11VideoProcessor,
    source: Size,
    output: Size,
    ring: Vec<(ID3D11Texture2D, ID3D11VideoProcessorOutputView)>,
    next: usize,
}

impl Nv12Converter {
    /// `ring_len` must exceed the number of frames the encoder may hold at once.
    pub fn new(gpu: &GpuDevice, source: Size, output: Size, ring_len: usize) -> Result<Self> {
        let video_device: ID3D11VideoDevice = gpu.device().cast()?;
        let video_context: ID3D11VideoContext1 = gpu.context().cast()?;
        let content = D3D11_VIDEO_PROCESSOR_CONTENT_DESC {
            InputFrameFormat: D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE,
            InputFrameRate: DXGI_RATIONAL {
                Numerator: 60,
                Denominator: 1,
            },
            InputWidth: source.width,
            InputHeight: source.height,
            OutputFrameRate: DXGI_RATIONAL {
                Numerator: 60,
                Denominator: 1,
            },
            OutputWidth: output.width,
            OutputHeight: output.height,
            Usage: D3D11_VIDEO_USAGE_OPTIMAL_SPEED,
        };
        // SAFETY: `content` is a fully initialised descriptor.
        let enumerator = unsafe { video_device.CreateVideoProcessorEnumerator(&content) }
            .context("create video processor enumerator")?;
        // SAFETY: plain queries on a valid enumerator.
        let (input_support, output_support) = unsafe {
            (
                enumerator.CheckVideoProcessorFormat(DXGI_FORMAT_B8G8R8A8_UNORM)?,
                enumerator.CheckVideoProcessorFormat(DXGI_FORMAT_NV12)?,
            )
        };
        let input_flag = D3D11_VIDEO_PROCESSOR_FORMAT_SUPPORT_INPUT.0.cast_unsigned();
        let output_flag = D3D11_VIDEO_PROCESSOR_FORMAT_SUPPORT_OUTPUT
            .0
            .cast_unsigned();
        if input_support & input_flag == 0 || output_support & output_flag == 0 {
            return Err(Error::new(
                E_FAIL,
                "the GPU video processor can't convert BGRA to NV12",
            ));
        }
        // SAFETY: `enumerator` came from this device; index 0 always exists.
        let processor = unsafe { video_device.CreateVideoProcessor(&enumerator, 0) }
            .context("create video processor")?;

        let source_rect = rect(source);
        let output_rect = rect(output);
        // SAFETY: setters on a valid processor; the rectangles outlive the calls.
        unsafe {
            video_context.VideoProcessorSetStreamFrameFormat(
                &processor,
                0,
                D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE,
            );
            video_context.VideoProcessorSetStreamAutoProcessingMode(&processor, 0, false);
            video_context.VideoProcessorSetStreamSourceRect(
                &processor,
                0,
                true,
                Some(&raw const source_rect),
            );
            video_context.VideoProcessorSetStreamDestRect(
                &processor,
                0,
                true,
                Some(&raw const output_rect),
            );
            video_context.VideoProcessorSetOutputTargetRect(
                &processor,
                true,
                Some(&raw const output_rect),
            );
            // Desktop pixels are full-range sRGB; H.264 wants BT.709 studio-range YCbCr.
            video_context.VideoProcessorSetStreamColorSpace1(
                &processor,
                0,
                DXGI_COLOR_SPACE_RGB_FULL_G22_NONE_P709,
            );
            video_context.VideoProcessorSetOutputColorSpace1(
                &processor,
                DXGI_COLOR_SPACE_YCBCR_STUDIO_G22_LEFT_P709,
            );
        }

        let mut ring = Vec::with_capacity(ring_len.max(1));
        for _ in 0..ring_len.max(1) {
            ring.push(output_texture(gpu, &video_device, &enumerator, output)?);
        }
        Ok(Self {
            video_device,
            video_context,
            enumerator,
            processor,
            source,
            output,
            ring,
            next: 0,
        })
    }

    #[must_use]
    pub fn source_size(&self) -> Size {
        self.source
    }

    #[must_use]
    pub fn output_size(&self) -> Size {
        self.output
    }

    /// Scales and converts `input` (BGRA at `source_size`) into the next ring texture and
    /// returns that texture.
    pub fn convert(&mut self, input: &ID3D11Texture2D) -> Result<ID3D11Texture2D> {
        let input_desc = D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC {
            FourCC: 0,
            ViewDimension: D3D11_VPIV_DIMENSION_TEXTURE2D,
            Anonymous: D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC_0 {
                Texture2D: D3D11_TEX2D_VPIV {
                    MipSlice: 0,
                    ArraySlice: 0,
                },
            },
        };
        let mut input_view = None;
        // SAFETY: `input` is a live texture and the out-pointer refers to a local.
        unsafe {
            self.video_device.CreateVideoProcessorInputView(
                input,
                &self.enumerator,
                &raw const input_desc,
                Some(&raw mut input_view),
            )
        }
        .context("create video processor input view")?;
        let (texture, output_view) = &self.ring[self.next];
        self.next = (self.next + 1) % self.ring.len();

        let streams = [D3D11_VIDEO_PROCESSOR_STREAM {
            Enable: BOOL::from(true),
            pInputSurface: ManuallyDrop::new(input_view),
            ..Default::default()
        }];
        // SAFETY: the processor, views and stream description are valid for the call.
        let result = unsafe {
            self.video_context
                .VideoProcessorBlt(&self.processor, output_view, 0, &streams)
        };
        // The stream description owns a reference to the input view; release it.
        let [stream] = streams;
        drop(ManuallyDrop::into_inner(stream.pInputSurface));
        result.context("convert frame to NV12")?;
        Ok(texture.clone())
    }
}

fn rect(size: Size) -> RECT {
    RECT {
        left: 0,
        top: 0,
        right: i32::try_from(size.width).unwrap_or(i32::MAX),
        bottom: i32::try_from(size.height).unwrap_or(i32::MAX),
    }
}

fn output_texture(
    gpu: &GpuDevice,
    video_device: &ID3D11VideoDevice,
    enumerator: &ID3D11VideoProcessorEnumerator,
    size: Size,
) -> Result<(ID3D11Texture2D, ID3D11VideoProcessorOutputView)> {
    let desc = D3D11_TEXTURE2D_DESC {
        Width: size.width,
        Height: size.height,
        MipLevels: 1,
        ArraySize: 1,
        Format: DXGI_FORMAT_NV12,
        SampleDesc: DXGI_SAMPLE_DESC {
            Count: 1,
            Quality: 0,
        },
        Usage: D3D11_USAGE_DEFAULT,
        BindFlags: D3D11_BIND_RENDER_TARGET.0.cast_unsigned(),
        CPUAccessFlags: 0,
        MiscFlags: 0,
    };
    let mut texture = None;
    // SAFETY: `desc` is fully initialised and the out-pointer refers to a local.
    unsafe {
        gpu.device()
            .CreateTexture2D(&raw const desc, None, Some(&raw mut texture))
    }
    .context("create NV12 texture")?;
    let texture: ID3D11Texture2D =
        texture.ok_or_else(|| Error::new(E_POINTER, "CreateTexture2D returned no texture"))?;

    let view_desc = D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC {
        ViewDimension: D3D11_VPOV_DIMENSION_TEXTURE2D,
        Anonymous: D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC_0 {
            Texture2D: D3D11_TEX2D_VPOV { MipSlice: 0 },
        },
    };
    let mut view = None;
    // SAFETY: the texture and enumerator are valid; the out-pointer refers to a local.
    unsafe {
        video_device.CreateVideoProcessorOutputView(
            &texture,
            enumerator,
            &raw const view_desc,
            Some(&raw mut view),
        )
    }
    .context("create video processor output view")?;
    let view = view.ok_or_else(|| Error::new(E_POINTER, "no video processor output view"))?;
    Ok((texture, view))
}
