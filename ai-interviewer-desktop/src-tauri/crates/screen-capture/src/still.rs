//! One picture of a display, for the evidence snapshots the server asks for (SP-14): Windows
//! Graphics Capture of the monitor, read back from the GPU once, then scaled to fit and
//! JPEG-encoded by the Windows Imaging Component (built into Windows, so no codec ships with
//! the app). Nothing here runs unless asked; the caller decides when capturing is allowed.

use std::time::{Duration, Instant};

use windows::Win32::Foundation::{E_FAIL, E_INVALIDARG, E_POINTER, HGLOBAL};
use windows::Win32::Graphics::Direct3D11::{
    D3D11_BOX, D3D11_CPU_ACCESS_READ, D3D11_MAP_READ, D3D11_MAPPED_SUBRESOURCE,
    D3D11_TEXTURE2D_DESC, D3D11_USAGE_STAGING, ID3D11Texture2D,
};
use windows::Win32::Graphics::Dxgi::Common::{DXGI_FORMAT_B8G8R8A8_UNORM, DXGI_SAMPLE_DESC};
use windows::Win32::Graphics::Imaging::{
    CLSID_WICImagingFactory, GUID_ContainerFormatJpeg, GUID_WICPixelFormat24bppBGR,
    GUID_WICPixelFormat32bppBGRA, IWICBitmapFrameEncode, IWICBitmapSource, IWICImagingFactory,
    WICBitmapDitherTypeNone, WICBitmapEncoderNoCache, WICBitmapInterpolationModeFant,
    WICBitmapPaletteTypeCustom,
};
use windows::Win32::System::Com::StructuredStorage::{CreateStreamOnHGlobal, IPropertyBag2};
use windows::Win32::System::Com::{
    CLSCTX_INPROC_SERVER, CoCreateInstance, STATFLAG_NONAME, STATSTG, STREAM_SEEK_SET,
};
use windows_core::{Error, Interface, Result};

use crate::capture::{CaptureOptions, CapturedFrame, MonitorCapture};
use crate::context::Context;
use crate::device::{GpuDevice, init_com_mta};
use crate::geometry::{Size, fit_even};
use crate::monitors;

/// A frame in system memory: 32-bit BGRA rows, `stride` bytes apart.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Still {
    pub size: Size,
    pub stride: u32,
    pub bgra: Vec<u8>,
}

impl Still {
    /// Whether the buffer holds every row the size and stride promise.
    fn check(&self) -> Result<()> {
        let row = u64::from(self.size.width) * 4;
        let needed = u64::from(self.stride) * u64::from(self.size.height.saturating_sub(1)) + row;
        if self.size.width == 0
            || self.size.height == 0
            || u64::from(self.stride) < row
            || (self.bgra.len() as u64) < needed
        {
            return Err(Error::new(
                E_INVALIDARG,
                "the frame's size, stride and buffer disagree",
            ));
        }
        Ok(())
    }
}

/// The primary display, captured once (waiting up to `timeout` for Windows' first frame).
pub fn capture_primary(timeout: Duration) -> Result<Still> {
    let monitor = monitors::enumerate()?
        .into_iter()
        .find(|monitor| monitor.primary)
        .ok_or_else(|| Error::new(E_FAIL, "no primary display"))?;
    capture_monitor(&monitor, timeout)
}

/// One frame of `monitor`, read back from the GPU.
pub fn capture_monitor(monitor: &monitors::MonitorInfo, timeout: Duration) -> Result<Still> {
    // A thread that already joined another apartment keeps it; capture works from either.
    let _ = init_com_mta();
    let gpu = GpuDevice::new().context("create the GPU device")?;
    let options = CaptureOptions {
        cursor: true,
        // As for the recording: Windows shows the candidate that the screen is being captured.
        border: true,
        min_interval: None,
    };
    let mut capture = MonitorCapture::start(&gpu, monitor.hmonitor(), options)?;
    let deadline = Instant::now() + timeout;
    loop {
        if let Some(frame) = capture.latest()? {
            return read_back(&gpu, &frame);
        }
        if Instant::now() >= deadline {
            return Err(Error::new(E_FAIL, "no frame arrived in time"));
        }
        std::thread::sleep(Duration::from_millis(10));
    }
}

/// Copies the frame's content into a CPU-readable texture and out into memory.
fn read_back(gpu: &GpuDevice, frame: &CapturedFrame) -> Result<Still> {
    let mut source_desc = D3D11_TEXTURE2D_DESC::default();
    // SAFETY: `source_desc` is a local the call fills in.
    unsafe { frame.texture.GetDesc(&raw mut source_desc) };
    // The pool's texture can be larger than the content just after a resolution change.
    let width = frame.size.width.min(source_desc.Width);
    let height = frame.size.height.min(source_desc.Height);
    if width == 0 || height == 0 {
        return Err(Error::new(E_FAIL, "the frame is empty"));
    }
    let desc = D3D11_TEXTURE2D_DESC {
        Width: width,
        Height: height,
        MipLevels: 1,
        ArraySize: 1,
        Format: DXGI_FORMAT_B8G8R8A8_UNORM,
        SampleDesc: DXGI_SAMPLE_DESC {
            Count: 1,
            Quality: 0,
        },
        Usage: D3D11_USAGE_STAGING,
        BindFlags: 0,
        CPUAccessFlags: D3D11_CPU_ACCESS_READ.0.cast_unsigned(),
        MiscFlags: 0,
    };
    let mut staging: Option<ID3D11Texture2D> = None;
    // SAFETY: `desc` is fully initialised and the out-pointer refers to a local.
    unsafe {
        gpu.device()
            .CreateTexture2D(&raw const desc, None, Some(&raw mut staging))
    }
    .context("create the read-back texture")?;
    let staging =
        staging.ok_or_else(|| Error::new(E_POINTER, "CreateTexture2D returned no texture"))?;
    let region = D3D11_BOX {
        left: 0,
        top: 0,
        front: 0,
        right: width,
        bottom: height,
        back: 1,
    };
    let context = gpu.context();
    // SAFETY: both textures belong to this device, are BGRA, and `region` lies inside both.
    unsafe {
        context.CopySubresourceRegion(
            &staging,
            0,
            0,
            0,
            0,
            &frame.texture,
            0,
            Some(&raw const region),
        );
    }
    let mut mapped = D3D11_MAPPED_SUBRESOURCE::default();
    // SAFETY: a staging texture created with CPU read access; `mapped` is a local.
    unsafe { context.Map(&staging, 0, D3D11_MAP_READ, 0, Some(&raw mut mapped)) }
        .context("map the read-back texture")?;
    let row = width as usize * 4;
    let pitch = mapped.RowPitch as usize;
    let mut bgra = vec![0u8; row * height as usize];
    if mapped.pData.is_null() || pitch < row {
        // SAFETY: mapped above.
        unsafe { context.Unmap(&staging, 0) };
        return Err(Error::new(E_FAIL, "the read-back texture couldn't be read"));
    }
    for (y, out) in bgra.chunks_exact_mut(row).enumerate() {
        // SAFETY: the mapping holds `height` rows of `RowPitch` bytes, each at least `row` long.
        unsafe {
            let source = mapped.pData.cast::<u8>().add(y * pitch);
            std::ptr::copy_nonoverlapping(source, out.as_mut_ptr(), row);
        }
    }
    // SAFETY: mapped above; nothing reads the mapping after this.
    unsafe { context.Unmap(&staging, 0) };
    Ok(Still {
        size: Size { width, height },
        stride: u32::try_from(row).unwrap_or(u32::MAX),
        bgra,
    })
}

/// Encodes `still` as a baseline JPEG no larger than `max` (scaled down with its shape kept),
/// at WIC's default quality (0.9): a 1280×720 screen is a few hundred kilobytes, well under
/// the server's 2 MiB.
pub fn encode_jpeg(still: &Still, max: Size) -> Result<Vec<u8>> {
    still.check()?;
    let target = fit_even(still.size, max);
    // Odd one-pixel sizes round down to zero; keep at least the frame itself then.
    let target = if target.width == 0 || target.height == 0 {
        still.size
    } else {
        target
    };
    let _ = init_com_mta();
    // SAFETY: COM is initialised on this thread; the class is the in-box WIC factory.
    let factory: IWICImagingFactory =
        unsafe { CoCreateInstance(&CLSID_WICImagingFactory, None, CLSCTX_INPROC_SERVER) }
            .context("create the WIC factory")?;
    // SAFETY: the buffer outlives the bitmap, which copies it (CreateBitmapFromMemory).
    let bitmap = unsafe {
        factory.CreateBitmapFromMemory(
            still.size.width,
            still.size.height,
            &GUID_WICPixelFormat32bppBGRA,
            still.stride,
            &still.bgra,
        )
    }
    .context("wrap the frame")?;
    let mut source: IWICBitmapSource = bitmap.cast()?;
    if target != still.size {
        // SAFETY: plain WIC calls on objects created above.
        let scaler = unsafe { factory.CreateBitmapScaler() }?;
        // SAFETY: the scaler reads `source`, which lives until the encoder has committed.
        unsafe {
            scaler.Initialize(
                &source,
                target.width,
                target.height,
                WICBitmapInterpolationModeFant,
            )
        }
        .context("scale the frame")?;
        source = scaler.cast()?;
    }
    // JPEG has no alpha: convert to 24-bit BGR first.
    // SAFETY: plain WIC calls on objects created above.
    let converter = unsafe { factory.CreateFormatConverter() }?;
    // SAFETY: the converter reads `source`, which lives until the encoder has committed.
    unsafe {
        converter.Initialize(
            &source,
            &GUID_WICPixelFormat24bppBGR,
            WICBitmapDitherTypeNone,
            None,
            0.0,
            WICBitmapPaletteTypeCustom,
        )
    }
    .context("convert the frame")?;

    // SAFETY: a new, growable memory stream that frees its memory on release.
    let stream = unsafe { CreateStreamOnHGlobal(HGLOBAL::default(), true) }?;
    // SAFETY: plain WIC calls on objects created above.
    let encoder = unsafe { factory.CreateEncoder(&GUID_ContainerFormatJpeg, std::ptr::null()) }
        .context("create the JPEG encoder")?;
    // SAFETY: the encoder writes into `stream`, which outlives it.
    unsafe { encoder.Initialize(&stream, WICBitmapEncoderNoCache) }?;
    let mut frame: Option<IWICBitmapFrameEncode> = None;
    let mut options: Option<IPropertyBag2> = None;
    // SAFETY: both out-pointers refer to locals.
    unsafe { encoder.CreateNewFrame(&raw mut frame, &raw mut options) }?;
    let frame = frame.ok_or_else(|| Error::new(E_POINTER, "no frame encoder"))?;
    // SAFETY: plain WIC calls on objects created above; the options keep WIC's defaults.
    unsafe {
        frame.Initialize(options.as_ref())?;
        frame.SetSize(target.width, target.height)?;
        let mut format = GUID_WICPixelFormat24bppBGR;
        frame.SetPixelFormat(&raw mut format)?;
        frame.WriteSource(&converter, std::ptr::null())?;
        frame.Commit()?;
        encoder.Commit()?;
    }

    let mut stat = STATSTG::default();
    // SAFETY: `stat` is a local; STATFLAG_NONAME leaves its name unallocated.
    unsafe { stream.Stat(&raw mut stat, STATFLAG_NONAME) }?;
    let length = usize::try_from(stat.cbSize)
        .map_err(|_| Error::new(E_FAIL, "the encoded picture is too large"))?;
    let mut bytes = vec![0u8; length];
    let mut read = 0u32;
    // SAFETY: the buffer holds `length` bytes; the stream is rewound to its start first.
    unsafe {
        stream.Seek(0, STREAM_SEEK_SET, None)?;
        stream
            .Read(
                bytes.as_mut_ptr().cast(),
                u32::try_from(length).unwrap_or(u32::MAX),
                Some(&raw mut read),
            )
            .ok()?;
    }
    bytes.truncate(read as usize);
    if bytes.len() < 4 || bytes[..2] != [0xFF, 0xD8] {
        return Err(Error::new(E_FAIL, "the encoder produced no JPEG"));
    }
    Ok(bytes)
}
