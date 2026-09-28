//! Windows Graphics Capture of one monitor, polled for the newest frame.

use crate::context::Context;
use crate::device::GpuDevice;
use crate::geometry::Size;
use std::time::Duration;
use windows::Foundation::TimeSpan;
use windows::Graphics::Capture::{
    Direct3D11CaptureFrame, Direct3D11CaptureFramePool, GraphicsCaptureItem, GraphicsCaptureSession,
};
use windows::Graphics::DirectX::Direct3D11::IDirect3DDevice;
use windows::Graphics::DirectX::DirectXPixelFormat;
use windows::Graphics::SizeInt32;
use windows::Win32::Graphics::Direct3D11::ID3D11Texture2D;
use windows::Win32::Graphics::Gdi::HMONITOR;
use windows::Win32::System::WinRT::Direct3D11::IDirect3DDxgiInterfaceAccess;
use windows::Win32::System::WinRT::Graphics::Capture::IGraphicsCaptureItemInterop;
use windows_core::{Interface, Result};

/// Capture options for one monitor.
#[derive(Debug, Clone, Copy)]
pub struct CaptureOptions {
    /// Draw the mouse pointer into frames.
    pub cursor: bool,
    /// Keep the yellow "being captured" border that Windows draws. Removing it needs
    /// Windows 11; older versions always show it.
    pub border: bool,
    /// Ask Windows not to deliver frames more often than this (Windows 11 24H2+).
    pub min_interval: Option<Duration>,
}

/// A captured frame. Its texture belongs to the capture pool until this value is dropped,
/// so convert it and drop it promptly.
pub struct CapturedFrame {
    pub texture: ID3D11Texture2D,
    pub size: Size,
    _frame: Direct3D11CaptureFrame,
}

/// An active capture of one monitor.
pub struct MonitorCapture {
    pool: Direct3D11CaptureFramePool,
    session: GraphicsCaptureSession,
    pool_size: SizeInt32,
    winrt_device: IDirect3DDevice,
    /// Frames Windows delivered, including ones skipped because a newer one arrived.
    pub delivered: u64,
    /// Times the monitor changed size and the pool was rebuilt.
    pub resized: u64,
}

impl MonitorCapture {
    pub fn start(gpu: &GpuDevice, monitor: HMONITOR, options: CaptureOptions) -> Result<Self> {
        let interop = windows_core::factory::<GraphicsCaptureItem, IGraphicsCaptureItemInterop>()?;
        // SAFETY: `monitor` is a display handle from EnumDisplayMonitors.
        let item: GraphicsCaptureItem =
            unsafe { interop.CreateForMonitor(monitor) }.context("capture item for monitor")?;
        let pool_size = item.Size()?;
        let pool = Direct3D11CaptureFramePool::CreateFreeThreaded(
            gpu.winrt(),
            DirectXPixelFormat::B8G8R8A8UIntNormalized,
            2,
            pool_size,
        )
        .context("create frame pool")?;
        let session = pool
            .CreateCaptureSession(&item)
            .context("create capture session")?;
        session.SetIsCursorCaptureEnabled(options.cursor)?;
        if !options.border {
            // Fails before Windows 11; the border then stays, which is acceptable.
            let _ = session.SetIsBorderRequired(false);
        }
        if let Some(interval) = options.min_interval {
            let ticks = i64::try_from(interval.as_nanos() / 100).unwrap_or(i64::MAX);
            // Fails before Windows 11 24H2; Windows then delivers every change.
            let _ = session.SetMinUpdateInterval(TimeSpan { Duration: ticks });
        }
        session.StartCapture().context("start capture")?;
        Ok(Self {
            pool,
            session,
            pool_size,
            winrt_device: gpu.winrt().clone(),
            delivered: 0,
            resized: 0,
        })
    }

    /// The newest frame delivered since the last call, or `None` when the screen hasn't
    /// changed. Older pending frames are released.
    pub fn latest(&mut self) -> Result<Option<CapturedFrame>> {
        let mut newest = None;
        loop {
            match self.pool.TryGetNextFrame() {
                Ok(frame) => {
                    self.delivered += 1;
                    newest = Some(frame);
                }
                // No pending frame comes back as a null object, reported as an empty error.
                Err(error) if error.code().is_ok() => break,
                Err(error) => return Err(error),
            }
        }
        let Some(frame) = newest else {
            return Ok(None);
        };
        let content = frame.ContentSize()?;
        if content.Width != self.pool_size.Width || content.Height != self.pool_size.Height {
            // The display changed resolution: rebuild the pool at the new size.
            self.pool.Recreate(
                &self.winrt_device,
                DirectXPixelFormat::B8G8R8A8UIntNormalized,
                2,
                content,
            )?;
            self.pool_size = content;
            self.resized += 1;
        }
        let access: IDirect3DDxgiInterfaceAccess = frame.Surface()?.cast()?;
        // SAFETY: the capture surface wraps a D3D11 texture, which is the interface requested.
        let texture: ID3D11Texture2D = unsafe { access.GetInterface()? };
        let size = Size {
            width: u32::try_from(content.Width).unwrap_or(0),
            height: u32::try_from(content.Height).unwrap_or(0),
        };
        Ok(Some(CapturedFrame {
            texture,
            size,
            _frame: frame,
        }))
    }

    /// The monitor's size when capture started or last changed.
    #[must_use]
    pub fn size(&self) -> Size {
        Size {
            width: u32::try_from(self.pool_size.Width).unwrap_or(0),
            height: u32::try_from(self.pool_size.Height).unwrap_or(0),
        }
    }
}

impl Drop for MonitorCapture {
    fn drop(&mut self) {
        let _ = self.session.Close();
        let _ = self.pool.Close();
    }
}
