// Live terminal view: five heaps, one trace, diverging in real time.
// Half-block cells (▀ with fg/bg = two arena rows per terminal line),
// truecolor by size class, dark = free.

use std::io::{self, Write};
use std::time::{Duration, Instant};

use crossterm::event::{self, Event, KeyCode, KeyEventKind};
use crossterm::{cursor, execute, terminal};

use crate::harness::Harness;
use crate::viz::{cell_color, class_color};
use crate::workload::KINDS;

const STRIP_W: usize = 112; // cells across
const STRIP_ROWS: usize = 4; // arena rows -> 2 terminal lines

pub fn run(mut harness: Harness) -> io::Result<()> {
    let mut out = io::stdout();
    terminal::enable_raw_mode()?;
    execute!(out, terminal::EnterAlternateScreen, cursor::Hide)?;
    let res = event_loop(&mut harness, &mut out);
    execute!(out, cursor::Show, terminal::LeaveAlternateScreen)?;
    terminal::disable_raw_mode()?;
    res
}

fn event_loop(harness: &mut Harness, out: &mut io::Stdout) -> io::Result<()> {
    let mut paused = false;
    let mut ops_per_frame: u64 = 3000;
    let mut ops_window: u64 = 0;
    let mut rate = 0.0f64;
    let mut last_rate_t = Instant::now();

    loop {
        let frame_start = Instant::now();
        if !paused {
            harness.run(ops_per_frame);
            ops_window += ops_per_frame;
        }
        if last_rate_t.elapsed() >= Duration::from_millis(500) {
            rate = ops_window as f64 / last_rate_t.elapsed().as_secs_f64();
            ops_window = 0;
            last_rate_t = Instant::now();
        }

        draw(harness, out, paused, rate, ops_per_frame)?;

        // keys (poll for whatever is left of the ~33ms frame)
        let budget = Duration::from_millis(33).saturating_sub(frame_start.elapsed());
        if event::poll(budget.max(Duration::from_millis(1)))? {
            if let Event::Key(k) = event::read()? {
                if k.kind != KeyEventKind::Press {
                    continue;
                }
                match k.code {
                    KeyCode::Char('q') | KeyCode::Esc => return Ok(()),
                    KeyCode::Char(' ') => paused = !paused,
                    KeyCode::Char('s') if paused => harness.run(ops_per_frame),
                    KeyCode::Char('f') => harness.workload.inject_spike(),
                    KeyCode::Char('r') => harness.set_workload(harness.workload.kind),
                    KeyCode::Char('w') => {
                        let i = KINDS
                            .iter()
                            .position(|&x| x == harness.workload.kind)
                            .unwrap();
                        harness.set_workload(KINDS[(i + 1) % KINDS.len()]);
                    }
                    KeyCode::Char(c @ '1'..='5') => {
                        harness.set_workload(KINDS[c as usize - '1' as usize]);
                    }
                    KeyCode::Char('+') | KeyCode::Char('=') => {
                        ops_per_frame = (ops_per_frame * 2).min(200_000)
                    }
                    KeyCode::Char('-') => ops_per_frame = (ops_per_frame / 2).max(250),
                    _ => {}
                }
            }
        }
    }
}

fn fg(s: &mut String, (r, g, b): (u8, u8, u8)) {
    s.push_str(&format!("\x1b[38;2;{r};{g};{b}m"));
}
fn bg(s: &mut String, (r, g, b): (u8, u8, u8)) {
    s.push_str(&format!("\x1b[48;2;{r};{g};{b}m"));
}

fn human(n: u32) -> String {
    if n >= 1 << 20 {
        format!("{:.1}M", n as f64 / (1 << 20) as f64)
    } else if n >= 1 << 10 {
        format!("{}K", n >> 10)
    } else {
        format!("{n}B")
    }
}

fn draw(
    harness: &Harness,
    out: &mut io::Stdout,
    paused: bool,
    rate: f64,
    opf: u64,
) -> io::Result<()> {
    let mut s = String::with_capacity(64 * 1024);
    s.push_str("\x1b[H"); // home (no full clear: avoids flicker)

    let state = if paused { "⏸ paused" } else { "▶ live" };
    s.push_str(&format!(
        "\x1b[0m\x1b[1m heapscape\x1b[0m · workload \x1b[1m{}\x1b[0m · {} · {:>7.0} ops/s · batch {}\x1b[K\r\n",
        harness.workload.kind.name(),
        state,
        rate,
        opf,
    ));
    s.push_str(" [1-5] workload  [w] next  [f] spike  [space] pause  [s] step  [+/-] speed  [r] reset  [q] quit\x1b[K\r\n");

    // legend: size classes
    s.push_str(" size ");
    for (i, label) in [
        "16", "32", "64", "128", "256", "512", "1K", "2K", "4K", "8K", "16K", "32K+",
    ]
    .iter()
    .enumerate()
    {
        fg(&mut s, class_color(i as u8));
        s.push('■');
        s.push_str("\x1b[0m");
        s.push_str(label);
        s.push(' ');
    }
    s.push_str("\x1b[K\r\n\x1b[K\r\n");

    let mut cells = vec![(0.0f32, 0u8); STRIP_W * STRIP_ROWS];
    for lane in &harness.lanes {
        lane.paint(&mut cells);
        let m = lane.metrics();
        s.push_str(&format!(
            " \x1b[1m{:<19}\x1b[0m util {:>5.1}%  ovh {:>5.1}%  frag {:>5.1}%  big {:>6}  fail {}\x1b[K\r\n",
            lane.alloc.name(),
            m.util * 100.0,
            m.overhead * 100.0,
            m.ext_frag * 100.0,
            human(m.largest_free),
            m.failures,
        ));
        for line in 0..STRIP_ROWS / 2 {
            s.push(' ');
            for x in 0..STRIP_W {
                let top = cells[(line * 2) * STRIP_W + x];
                let bot = cells[(line * 2 + 1) * STRIP_W + x];
                fg(&mut s, cell_color(top.0, top.1));
                bg(&mut s, cell_color(bot.0, bot.1));
                s.push('▀');
            }
            s.push_str("\x1b[0m\x1b[K\r\n");
        }
        s.push_str("\x1b[K\r\n");
    }
    s.push_str("\x1b[J"); // clear below

    out.write_all(s.as_bytes())?;
    out.flush()
}
