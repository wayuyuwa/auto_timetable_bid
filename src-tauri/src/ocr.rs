//! Captcha OCR using the ddddocr ONNX model, mirroring src/utils/ocr/OCR.py.
//!
//! The model and charset are embedded so the app is self-contained and offline.
//! Preprocessing and CTC decoding match the Python exactly (verified output
//! "3mx54" on the sample Kaptcha.jpg).

use image::imageops::FilterType;
use once_cell::sync::OnceCell;
use ort::session::{builder::GraphOptimizationLevel, Session};
use ort::value::Tensor;
use parking_lot::Mutex;

// ort's builder error type is not Send+Sync, so this module uses String errors
// (which are) rather than anyhow.
type Result<T> = std::result::Result<T, String>;

static MODEL: &[u8] = include_bytes!("../../src/utils/ocr/common_old.onnx");
static CHARSET_JSON: &str = include_str!("../../src/utils/ocr/common_old_charset.json");

struct Model {
    session: Mutex<Session>,
    charset: Vec<String>,
}

static MODEL_CELL: OnceCell<Model> = OnceCell::new();

fn model() -> Result<&'static Model> {
    MODEL_CELL.get_or_try_init(|| {
        let env = ort::init().build().map_err(|e| e.to_string())?;
        let session = Session::builder(&env)
            .map_err(|e| e.to_string())?
            .with_optimization_level(GraphOptimizationLevel::Level3)
            .map_err(|e| e.to_string())?
            .commit_from_memory(MODEL)
            .map_err(|e| e.to_string())?;
        let charset: Vec<String> =
            serde_json::from_str(CHARSET_JSON).map_err(|e| e.to_string())?;
        Ok(Model {
            session: Mutex::new(session),
            charset,
        })
    })
}

/// Recognise the captcha text in a JPEG/PNG image.
pub fn solve(image_bytes: &[u8]) -> Result<String> {
    let model = model()?;
    let (shape, data) = preprocess(image_bytes)?;

    let tensor = Tensor::from_array((shape, data)).map_err(|e| e.to_string())?;
    let mut session = model.session.lock();
    let outputs = session
        .run(ort::inputs!["input1" => tensor])
        .map_err(|e| e.to_string())?;

    // Output is int64 [1, seqlen]: character indices with argmax already applied.
    let (_shape, indices) = outputs["output"]
        .try_extract_tensor::<i64>()
        .map_err(|e| e.to_string())?;
    Ok(ctc_decode(indices, &model.charset))
}

/// Grayscale, resize to height 64, normalize to [-1, 1], NCHW [1,1,64,W].
fn preprocess(image_bytes: &[u8]) -> Result<([usize; 4], Vec<f32>)> {
    let gray = image::load_from_memory(image_bytes)
        .map_err(|e| format!("decode captcha image: {e}"))?
        .to_luma8();
    let (w, h) = gray.dimensions();
    if h == 0 || w == 0 {
        return Err("empty captcha image".to_string());
    }
    // Python uses int() truncation for the new width.
    let new_w = ((64.0 * w as f32) / h as f32) as u32;
    let new_w = new_w.max(1);
    let resized = image::imageops::resize(&gray, new_w, 64, FilterType::Lanczos3);

    let data: Vec<f32> = resized
        .into_raw()
        .into_iter()
        .map(|b| (b as f32 / 255.0 - 0.5) / 0.5)
        .collect();

    Ok(([1, 1, 64, new_w as usize], data))
}

/// Greedy CTC collapse: drop repeats, then blanks (index 0); map via charset.
fn ctc_decode(indices: &[i64], charset: &[String]) -> String {
    let mut out = String::new();
    let mut prev: i64 = -1;
    for &idx in indices {
        if idx == prev {
            continue;
        }
        prev = idx;
        if idx == 0 {
            continue;
        }
        if let Some(ch) = charset.get(idx as usize) {
            out.push_str(ch);
        }
    }
    out
}

#[cfg(test)]
mod tests {
    #[test]
    fn solves_sample_captcha() {
        let bytes = include_bytes!("../../src/utils/ocr/Kaptcha.jpg");
        let text = super::solve(bytes).expect("ocr should succeed");
        assert_eq!(text, "3mx54");
    }
}
