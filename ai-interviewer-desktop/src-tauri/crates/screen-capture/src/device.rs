//! The D3D11 device shared by capture, conversion and encoding on one thread.

use windows::Graphics::DirectX::Direct3D11::IDirect3DDevice;
use windows::Win32::Foundation::{E_POINTER, HMODULE};
use windows::Win32::Graphics::Direct3D::{
    D3D_DRIVER_TYPE_HARDWARE, D3D_FEATURE_LEVEL_11_0, D3D_FEATURE_LEVEL_11_1,
};
use windows::Win32::Graphics::Direct3D11::{
    D3D11_CREATE_DEVICE_BGRA_SUPPORT, D3D11_CREATE_DEVICE_VIDEO_SUPPORT, D3D11_SDK_VERSION,
    D3D11CreateDevice, ID3D11Device, ID3D11DeviceContext, ID3D11Multithread,
};
use windows::Win32::Graphics::Dxgi::{IDXGIAdapter, IDXGIDevice};
use windows::Win32::System::Com::{COINIT_MULTITHREADED, CoInitializeEx};
use windows::Win32::System::WinRT::Direct3D11::CreateDirect3D11DeviceFromDXGIDevice;
use windows_core::{Error, Interface, Result};

/// Joins the calling thread to the COM multithreaded apartment, which WinRT capture and
/// Media Foundation need. Calling it again on the same thread is harmless.
pub fn init_com_mta() -> Result<()> {
    // SAFETY: no reserved pointer is passed and COINIT_MULTITHREADED is a valid mode.
    unsafe { CoInitializeEx(None, COINIT_MULTITHREADED) }.ok()
}

/// A hardware D3D11 device with BGRA and video support, protected for use from several
/// threads (capture, the video processor and the encoder all touch it).
pub struct GpuDevice {
    device: ID3D11Device,
    context: ID3D11DeviceContext,
    winrt: IDirect3DDevice,
    adapter: String,
}

impl GpuDevice {
    pub fn new() -> Result<Self> {
        let mut device = None;
        let mut context = None;
        // SAFETY: the out-pointers refer to live locals for the duration of the call.
        unsafe {
            D3D11CreateDevice(
                None::<&IDXGIAdapter>,
                D3D_DRIVER_TYPE_HARDWARE,
                HMODULE::default(),
                D3D11_CREATE_DEVICE_BGRA_SUPPORT | D3D11_CREATE_DEVICE_VIDEO_SUPPORT,
                Some(&[D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0]),
                D3D11_SDK_VERSION,
                Some(&raw mut device),
                None,
                Some(&raw mut context),
            )?;
        }
        let device: ID3D11Device =
            device.ok_or_else(|| Error::new(E_POINTER, "D3D11CreateDevice returned no device"))?;
        let context = context
            .ok_or_else(|| Error::new(E_POINTER, "D3D11CreateDevice returned no context"))?;

        let multithread: ID3D11Multithread = device.cast()?;
        // SAFETY: a plain setter on a valid interface; the previous state it returns is unused.
        let _ = unsafe { multithread.SetMultithreadProtected(true) };

        let dxgi: IDXGIDevice = device.cast()?;
        // SAFETY: `dxgi` is the DXGI view of the device created above.
        let winrt: IDirect3DDevice =
            unsafe { CreateDirect3D11DeviceFromDXGIDevice(&dxgi)? }.cast()?;
        // SAFETY: valid interfaces; GetDesc fills a plain struct.
        let description = unsafe { dxgi.GetAdapter()?.GetDesc()? }.Description;
        let end = description
            .iter()
            .position(|&c| c == 0)
            .unwrap_or(description.len());
        let adapter = String::from_utf16_lossy(&description[..end]);

        Ok(Self {
            device,
            context,
            winrt,
            adapter,
        })
    }

    #[must_use]
    pub fn device(&self) -> &ID3D11Device {
        &self.device
    }

    #[must_use]
    pub fn context(&self) -> &ID3D11DeviceContext {
        &self.context
    }

    /// The WinRT wrapper that Windows Graphics Capture needs.
    #[must_use]
    pub fn winrt(&self) -> &IDirect3DDevice {
        &self.winrt
    }

    /// The GPU's name, for reports.
    #[must_use]
    pub fn adapter_name(&self) -> &str {
        &self.adapter
    }
}
