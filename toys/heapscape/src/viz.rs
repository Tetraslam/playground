// Color + image output: size-class palette shared by the TUI and PNG
// snapshots, a tiny PPM writer (converted to PNG via `magick` when
// available), and a largest-free-block-over-time chart.

use std::io::Write;
use std::path::Path;
use std::process::Command;

/// palette: size class 0 (16 B) = cool cyan, up to class 11 (32 KiB+) = hot magenta
pub fn class_color(class: u8) -> (u8, u8, u8) {
    let t = class as f32 / 11.0;
    let hue = 190.0 - 220.0 * t; // 190° cyan -> -30° ≡ 330° magenta
    hsv(hue.rem_euclid(360.0), 0.75, 0.95)
}

pub const FREE: (u8, u8, u8) = (24, 24, 30);

pub fn cell_color(coverage: f32, class: u8) -> (u8, u8, u8) {
    if coverage <= 0.02 {
        return FREE;
    }
    let (r, g, b) = class_color(class);
    let k = 0.25 + 0.75 * coverage;
    (
        (FREE.0 as f32 + (r as f32 - FREE.0 as f32) * k) as u8,
        (FREE.1 as f32 + (g as f32 - FREE.1 as f32) * k) as u8,
        (FREE.2 as f32 + (b as f32 - FREE.2 as f32) * k) as u8,
    )
}

fn hsv(h: f32, s: f32, v: f32) -> (u8, u8, u8) {
    let c = v * s;
    let x = c * (1.0 - ((h / 60.0) % 2.0 - 1.0).abs());
    let m = v - c;
    let (r, g, b) = match (h / 60.0) as u32 % 6 {
        0 => (c, x, 0.0),
        1 => (x, c, 0.0),
        2 => (0.0, c, x),
        3 => (0.0, x, c),
        4 => (x, 0.0, c),
        _ => (c, 0.0, x),
    };
    (
        ((r + m) * 255.0) as u8,
        ((g + m) * 255.0) as u8,
        ((b + m) * 255.0) as u8,
    )
}

pub struct Canvas {
    pub w: usize,
    pub h: usize,
    pub px: Vec<(u8, u8, u8)>,
}

impl Canvas {
    pub fn new(w: usize, h: usize, bg: (u8, u8, u8)) -> Self {
        Canvas {
            w,
            h,
            px: vec![bg; w * h],
        }
    }

    pub fn set(&mut self, x: usize, y: usize, c: (u8, u8, u8)) {
        if x < self.w && y < self.h {
            self.px[y * self.w + x] = c;
        }
    }

    pub fn fill_rect(&mut self, x: usize, y: usize, w: usize, h: usize, c: (u8, u8, u8)) {
        for yy in y..(y + h).min(self.h) {
            for xx in x..(x + w).min(self.w) {
                self.px[yy * self.w + xx] = c;
            }
        }
    }

    /// vertical-interpolated polyline segment (good enough for charts)
    pub fn line(&mut self, x0: usize, y0: usize, x1: usize, y1: usize, c: (u8, u8, u8)) {
        let steps = (x1.saturating_sub(x0)).max(y0.abs_diff(y1)).max(1);
        for i in 0..=steps {
            let t = i as f32 / steps as f32;
            let x = x0 as f32 + (x1 as f32 - x0 as f32) * t;
            let y = y0 as f32 + (y1 as f32 - y0 as f32) * t;
            self.set(x as usize, y as usize, c);
            self.set(x as usize, y as usize + 1, c); // 2px thick
        }
    }

    /// write PPM, then try to convert to PNG with `magick` (keeps PPM if not)
    pub fn save(&self, path_png: &Path) -> std::io::Result<()> {
        let ppm = path_png.with_extension("ppm");
        let mut f = std::fs::File::create(&ppm)?;
        write!(f, "P6\n{} {}\n255\n", self.w, self.h)?;
        let mut buf = Vec::with_capacity(self.w * self.h * 3);
        for &(r, g, b) in &self.px {
            buf.extend_from_slice(&[r, g, b]);
        }
        f.write_all(&buf)?;
        drop(f);
        let ok = Command::new("magick")
            .arg(&ppm)
            .arg(path_png)
            .status()
            .map(|s| s.success())
            .unwrap_or(false);
        if ok {
            std::fs::remove_file(&ppm)?;
        }
        Ok(())
    }
}
