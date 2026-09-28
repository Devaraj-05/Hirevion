//! One MP4 segment: a Media Foundation H.264 sink writer that encodes GPU textures and
//! writes the file into memory (nothing touches the disk until the caller decides).
//!
//! The file goes into a WinRT `InMemoryRandomAccessStream`: the MPEG-4 sink rejects byte
//! streams wrapped around an `HGLOBAL` `IStream` (`BeginWriting` fails with E_INVALIDARG).

use hv_screen_capture::context::Context;
use hv_screen_capture::device::GpuDevice;
use hv_screen_capture::geometry::Size;
use windows::Storage::Streams::InMemoryRandomAccessStream;
use windows::Win32::Foundation::E_POINTER;
use windows::Win32::Graphics::Direct3D11::ID3D11Texture2D;
use windows::Win32::Media::MediaFoundation::{
    CODECAPI_AVEncCommonMeanBitRate, CODECAPI_AVEncCommonRateControlMode, CODECAPI_AVEncMPVGOPSize,
    IMF2DBuffer, IMFAttributes, IMFDXGIDeviceManager, IMFMediaType, IMFSinkWriter, IMFSinkWriterEx,
    IMFTransform, MF_MT_AVG_BITRATE, MF_MT_FRAME_RATE, MF_MT_FRAME_SIZE, MF_MT_INTERLACE_MODE,
    MF_MT_MAJOR_TYPE, MF_MT_MAX_KEYFRAME_SPACING, MF_MT_MPEG2_PROFILE, MF_MT_PIXEL_ASPECT_RATIO,
    MF_MT_SUBTYPE, MF_MT_TRANSFER_FUNCTION, MF_MT_VIDEO_NOMINAL_RANGE, MF_MT_VIDEO_PRIMARIES,
    MF_MT_YUV_MATRIX, MF_READWRITE_ENABLE_HARDWARE_TRANSFORMS, MF_SINK_WRITER_D3D_MANAGER,
    MF_TRANSCODE_CONTAINERTYPE, MF_VERSION, MFCreateAttributes, MFCreateDXGIDeviceManager,
    MFCreateDXGISurfaceBuffer, MFCreateMFByteStreamOnStreamEx, MFCreateMediaType, MFCreateSample,
    MFCreateSinkWriterFromURL, MFMediaType_Video, MFNominalRange_16_235, MFSTARTUP_FULL, MFStartup,
    MFT_CATEGORY_VIDEO_ENCODER, MFT_CATEGORY_VIDEO_PROCESSOR, MFT_ENUM_HARDWARE_URL_Attribute,
    MFT_FRIENDLY_NAME_Attribute, MFTranscodeContainerType_MPEG4, MFVideoFormat_H264,
    MFVideoFormat_NV12, MFVideoInterlace_Progressive, MFVideoPrimaries_BT709, MFVideoTransFunc_709,
    MFVideoTransferMatrix_BT709, eAVEncCommonRateControlMode_UnconstrainedVBR,
    eAVEncH264VProfile_Main,
};
use windows::Win32::System::Com::{
    CoTaskMemFree, IStream, STATFLAG_NONAME, STATSTG, STREAM_SEEK_SET,
};
use windows::Win32::System::WinRT::CreateStreamOverRandomAccessStream;
use windows_core::{Error, GUID, Interface, PCWSTR, PWSTR, Result};

/// Encoder settings shared by every segment of one display.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct EncoderConfig {
    pub size: Size,
    pub fps: u32,
    pub bitrate: u32,
    pub gop_frames: u32,
    /// Allow hardware encoders (Quick Sync, NVENC, AMF). `false` forces Microsoft's
    /// software encoder, for comparison.
    pub hardware: bool,
}

/// Starts Media Foundation for the process. Reference counted, so repeated calls are fine.
pub fn startup() -> Result<()> {
    // SAFETY: plain call with the SDK version constant.
    unsafe { MFStartup(MF_VERSION, MFSTARTUP_FULL) }.context("start Media Foundation")
}

/// Shares one D3D11 device with every encoder on a thread.
pub fn device_manager(gpu: &GpuDevice) -> Result<IMFDXGIDeviceManager> {
    let mut token = 0u32;
    let mut manager = None;
    // SAFETY: both out-pointers refer to locals.
    unsafe { MFCreateDXGIDeviceManager(&raw mut token, &raw mut manager) }
        .context("create DXGI device manager")?;
    let manager = manager.ok_or_else(|| Error::new(E_POINTER, "no DXGI device manager"))?;
    // SAFETY: the device is a valid D3D11 device and `token` came from the call above.
    unsafe { manager.ResetDevice(gpu.device(), token) }.context("share the D3D11 device")?;
    Ok(manager)
}

/// An MP4 file being encoded in memory.
pub struct SegmentWriter {
    writer: IMFSinkWriter,
    memory: InMemoryRandomAccessStream,
    index: u32,
    frames: u32,
    transforms: String,
}

impl SegmentWriter {
    pub fn new(manager: &IMFDXGIDeviceManager, config: &EncoderConfig) -> Result<Self> {
        // SAFETY: every call below receives valid, fully initialised arguments; the objects
        // they return are owned by `Self` and released on drop.
        unsafe {
            let memory = InMemoryRandomAccessStream::new().context("memory stream")?;
            let byte_stream = MFCreateMFByteStreamOnStreamEx(&memory).context("byte stream")?;

            let attributes = attribute_store(3)?;
            attributes.SetGUID(&MF_TRANSCODE_CONTAINERTYPE, &MFTranscodeContainerType_MPEG4)?;
            attributes.SetUINT32(
                &MF_READWRITE_ENABLE_HARDWARE_TRANSFORMS,
                u32::from(config.hardware),
            )?;
            attributes.SetUnknown(&MF_SINK_WRITER_D3D_MANAGER, manager)?;
            let writer = MFCreateSinkWriterFromURL(PCWSTR::null(), &byte_stream, &attributes)
                .context("create MP4 sink writer")?;

            let output = video_type(&MFVideoFormat_H264, config)?;
            output.SetUINT32(&MF_MT_AVG_BITRATE, config.bitrate)?;
            output.SetUINT32(
                &MF_MT_MPEG2_PROFILE,
                eAVEncH264VProfile_Main.0.cast_unsigned(),
            )?;
            output.SetUINT32(&MF_MT_MAX_KEYFRAME_SPACING, config.gop_frames)?;
            let index = writer.AddStream(&output).context("add H.264 stream")?;

            let input = video_type(&MFVideoFormat_NV12, config)?;
            let encoding = attribute_store(3)?;
            encoding.SetUINT32(&CODECAPI_AVEncMPVGOPSize, config.gop_frames)?;
            encoding.SetUINT32(
                &CODECAPI_AVEncCommonRateControlMode,
                eAVEncCommonRateControlMode_UnconstrainedVBR
                    .0
                    .cast_unsigned(),
            )?;
            encoding.SetUINT32(&CODECAPI_AVEncCommonMeanBitRate, config.bitrate)?;
            writer
                .SetInputMediaType(index, &input, &encoding)
                .context("set NV12 input and encoder settings")?;
            writer.BeginWriting().context("begin writing")?;

            let transforms = describe_transforms(&writer, index);
            Ok(Self {
                writer,
                memory,
                index,
                frames: 0,
                transforms,
            })
        }
    }

    /// Queues one NV12 frame. `time` and `duration` are in 100 ns units from the start of
    /// this segment.
    pub fn write(&mut self, texture: &ID3D11Texture2D, time: i64, duration: i64) -> Result<()> {
        // SAFETY: the texture is a live NV12 texture on the device the encoder uses.
        unsafe {
            let buffer = MFCreateDXGISurfaceBuffer(&ID3D11Texture2D::IID, texture, 0, false)
                .context("wrap texture")?;
            let two_d: IMF2DBuffer = buffer.cast()?;
            buffer.SetCurrentLength(two_d.GetContiguousLength()?)?;
            let sample = MFCreateSample()?;
            sample.AddBuffer(&buffer)?;
            sample.SetSampleTime(time)?;
            sample.SetSampleDuration(duration)?;
            self.writer
                .WriteSample(self.index, &sample)
                .context("encode frame")?;
        }
        self.frames += 1;
        Ok(())
    }

    /// Frames written so far.
    #[must_use]
    pub fn frames(&self) -> u32 {
        self.frames
    }

    /// The transforms Media Foundation chose, for example
    /// `encoder: Intel(R) Quick Sync Video H.264 Encoder MFT (hardware)`.
    #[must_use]
    pub fn transforms(&self) -> &str {
        &self.transforms
    }

    /// Flushes the encoder, finishes the MP4 and returns its bytes.
    pub fn finish(self) -> Result<Vec<u8>> {
        // SAFETY: valid objects; the read targets a buffer of the reported size.
        unsafe {
            self.writer.Finalize().context("finish MP4")?;
            let stream: IStream =
                CreateStreamOverRandomAccessStream(&self.memory).context("read memory stream")?;
            let mut stat = STATSTG::default();
            stream.Stat(&raw mut stat, STATFLAG_NONAME)?;
            let length = usize::try_from(stat.cbSize).unwrap_or(0);
            stream.Seek(0, STREAM_SEEK_SET, None)?;
            let mut bytes = vec![0u8; length];
            let mut read = 0u32;
            stream
                .Read(
                    bytes.as_mut_ptr().cast(),
                    u32::try_from(length).unwrap_or(u32::MAX),
                    Some(&raw mut read),
                )
                .ok()?;
            bytes.truncate(read as usize);
            Ok(bytes)
        }
    }
}

// SAFETY: Media Foundation objects created in the multithreaded apartment may be called
// from any MTA thread. A writer is only ever used by one thread at a time: ownership moves
// to the finalizer thread (also MTA) once the recorder stops writing to it.
unsafe impl Send for SegmentWriter {}

/// Packs two 32-bit values into one attribute value, as `MFSetAttributeSize` and
/// `MFSetAttributeRatio` do.
#[must_use]
pub fn pack(high: u32, low: u32) -> u64 {
    (u64::from(high) << 32) | u64::from(low)
}

fn attribute_store(capacity: u32) -> Result<IMFAttributes> {
    let mut attributes = None;
    // SAFETY: the out-pointer refers to a local.
    unsafe { MFCreateAttributes(&raw mut attributes, capacity)? };
    attributes.ok_or_else(|| Error::new(E_POINTER, "no attribute store"))
}

fn video_type(subtype: &GUID, config: &EncoderConfig) -> Result<IMFMediaType> {
    // SAFETY: plain attribute setters on a new media type.
    unsafe {
        let media_type = MFCreateMediaType()?;
        media_type.SetGUID(&MF_MT_MAJOR_TYPE, &MFMediaType_Video)?;
        media_type.SetGUID(&MF_MT_SUBTYPE, subtype)?;
        media_type.SetUINT32(
            &MF_MT_INTERLACE_MODE,
            MFVideoInterlace_Progressive.0.cast_unsigned(),
        )?;
        media_type.SetUINT64(
            &MF_MT_FRAME_SIZE,
            pack(config.size.width, config.size.height),
        )?;
        media_type.SetUINT64(&MF_MT_FRAME_RATE, pack(config.fps, 1))?;
        media_type.SetUINT64(&MF_MT_PIXEL_ASPECT_RATIO, pack(1, 1))?;
        // BT.709 studio range, matching what the GPU converter produces.
        media_type.SetUINT32(
            &MF_MT_YUV_MATRIX,
            MFVideoTransferMatrix_BT709.0.cast_unsigned(),
        )?;
        media_type.SetUINT32(
            &MF_MT_VIDEO_NOMINAL_RANGE,
            MFNominalRange_16_235.0.cast_unsigned(),
        )?;
        media_type.SetUINT32(
            &MF_MT_VIDEO_PRIMARIES,
            MFVideoPrimaries_BT709.0.cast_unsigned(),
        )?;
        media_type.SetUINT32(
            &MF_MT_TRANSFER_FUNCTION,
            MFVideoTransFunc_709.0.cast_unsigned(),
        )?;
        Ok(media_type)
    }
}

fn describe_transforms(writer: &IMFSinkWriter, index: u32) -> String {
    let Ok(writer) = writer.cast::<IMFSinkWriterEx>() else {
        return String::from("unknown");
    };
    let mut descriptions = Vec::new();
    for position in 0..16 {
        let mut category = GUID::zeroed();
        let mut transform = None;
        // SAFETY: out-pointers refer to locals; an index past the end returns an error.
        let found = unsafe {
            writer.GetTransformForStream(
                index,
                position,
                Some(&raw mut category),
                &raw mut transform,
            )
        };
        let (Ok(()), Some(transform)) = (found, transform) else {
            break;
        };
        let kind = match category {
            c if c == MFT_CATEGORY_VIDEO_ENCODER => "encoder",
            c if c == MFT_CATEGORY_VIDEO_PROCESSOR => "processor",
            _ => "transform",
        };
        let name = friendly_name(&transform).unwrap_or_else(|| String::from("unnamed"));
        let hardware = if is_hardware(&transform) {
            " (hardware)"
        } else {
            ""
        };
        descriptions.push(format!("{kind}: {name}{hardware}"));
    }
    if descriptions.is_empty() {
        String::from("none reported")
    } else {
        descriptions.join(", ")
    }
}

fn friendly_name(transform: &IMFTransform) -> Option<String> {
    // SAFETY: GetAllocatedString hands back a CoTaskMem string that is freed below.
    unsafe {
        let attributes = transform.GetAttributes().ok()?;
        let mut value = PWSTR::null();
        let mut length = 0u32;
        attributes
            .GetAllocatedString(
                &MFT_FRIENDLY_NAME_Attribute,
                &raw mut value,
                &raw mut length,
            )
            .ok()?;
        let name = value.to_string().ok();
        CoTaskMemFree(Some(value.0 as *const core::ffi::c_void));
        name
    }
}

fn is_hardware(transform: &IMFTransform) -> bool {
    // SAFETY: plain attribute query.
    unsafe {
        transform
            .GetAttributes()
            .and_then(|attributes| attributes.GetStringLength(&MFT_ENUM_HARDWARE_URL_Attribute))
            .is_ok()
    }
}

#[cfg(test)]
mod tests {
    use super::pack;

    #[test]
    fn packs_size_and_ratio_values_like_media_foundation() {
        assert_eq!(pack(1920, 1080), 0x0000_0780_0000_0438);
        assert_eq!(pack(15, 1), (15u64 << 32) | 1);
    }
}
