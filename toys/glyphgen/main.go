// glyphgen — generate procedural fantasy "glyphs" as SVG.
//
// A tiny worldbuilding toy: given a seed word (say, a Qurwenyan name), it
// deterministically draws a sigil on a hex-ish grid by walking a pseudo-random
// path and decorating nodes. Same word -> same glyph, always.
//
//	go run ./toys/glyphgen --word Qurwenya --out scratch/qurwenya.svg
//	go run ./toys/glyphgen --word Aire --size 512
//
// No external deps — stdlib only. Output is an SVG you can open or screenshot.
package main

import (
	"flag"
	"fmt"
	"hash/fnv"
	"math"
	"os"
	"strings"
)

func main() {
	word := flag.String("word", "playground", "seed word for the glyph")
	out := flag.String("out", "", "output SVG path (default: stdout)")
	size := flag.Int("size", 400, "SVG canvas size in px")
	flag.Parse()

	svg := generate(*word, *size)

	if *out == "" {
		fmt.Print(svg)
		return
	}
	if err := os.MkdirAll(dir(*out), 0o755); err != nil {
		fmt.Fprintln(os.Stderr, "glyphgen:", err)
		os.Exit(1)
	}
	if err := os.WriteFile(*out, []byte(svg), 0o644); err != nil {
		fmt.Fprintln(os.Stderr, "glyphgen:", err)
		os.Exit(1)
	}
	fmt.Fprintf(os.Stderr, "glyphgen: wrote %s (glyph for %q)\n", *out, *word)
}

func dir(p string) string {
	if i := strings.LastIndex(p, "/"); i >= 0 {
		return p[:i]
	}
	return "."
}

// rng is a tiny deterministic PRNG (splitmix64) seeded from the word.
type rng struct{ s uint64 }

func newRNG(seed string) *rng {
	h := fnv.New64a()
	_, _ = h.Write([]byte(seed))
	return &rng{s: h.Sum64()}
}

func (r *rng) next() uint64 {
	r.s += 0x9e3779b97f4a7c15
	z := r.s
	z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9
	z = (z ^ (z >> 27)) * 0x94d049bb133111eb
	return z ^ (z >> 31)
}

func (r *rng) intn(n int) int { return int(r.next() % uint64(n)) }
func (r *rng) float() float64 { return float64(r.next()>>11) / float64(1<<53) }

func generate(word string, size int) string {
	r := newRNG(word)
	c := float64(size) / 2
	radius := float64(size) * 0.38

	// A ring of nodes; the count + palette derive from the word.
	nodes := 6 + r.intn(6) // 6..11
	hue := r.intn(360)
	stroke := fmt.Sprintf("hsl(%d, 70%%, 60%%)", hue)
	accent := fmt.Sprintf("hsl(%d, 80%%, 70%%)", (hue+140)%360)
	bg := fmt.Sprintf("hsl(%d, 30%%, 8%%)", hue)

	pts := make([][2]float64, nodes)
	for i := 0; i < nodes; i++ {
		ang := 2 * math.Pi * float64(i) / float64(nodes)
		pts[i] = [2]float64{c + radius*math.Cos(ang), c + radius*math.Sin(ang)}
	}

	var b strings.Builder
	fmt.Fprintf(&b, `<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">`, size, size, size, size)
	fmt.Fprintf(&b, `<rect width="%d" height="%d" fill="%s"/>`, size, size, bg)
	fmt.Fprintf(&b, `<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="%s" stroke-width="1.5" opacity="0.4"/>`, c, c, radius, stroke)

	// Walk a path that visits nodes in a word-derived order, connecting them.
	visited := make([]int, nodes)
	cur := r.intn(nodes)
	fmt.Fprintf(&b, `<path d="M %.1f %.1f`, pts[cur][0], pts[cur][1])
	for step := 0; step < nodes; step++ {
		visited[cur] = 1
		// jump by a word-derived stride to make a star/sigil pattern
		stride := 1 + r.intn(nodes-1)
		cur = (cur + stride) % nodes
		fmt.Fprintf(&b, ` L %.1f %.1f`, pts[cur][0], pts[cur][1])
	}
	fmt.Fprintf(&b, ` Z" fill="none" stroke="%s" stroke-width="2.5" stroke-linejoin="round"/>`, stroke)

	// Decorate each node with a small accent circle + occasional rune tick.
	for _, p := range pts {
		rad := 3.0 + r.float()*4
		fmt.Fprintf(&b, `<circle cx="%.1f" cy="%.1f" r="%.1f" fill="%s"/>`, p[0], p[1], rad, accent)
		if r.float() > 0.5 {
			dx := (p[0] - c) * 0.12
			dy := (p[1] - c) * 0.12
			fmt.Fprintf(&b, `<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="1.5"/>`,
				p[0]-dx, p[1]-dy, p[0]+dx, p[1]+dy, accent)
		}
	}

	// A central mark.
	fmt.Fprintf(&b, `<circle cx="%.1f" cy="%.1f" r="%.1f" fill="none" stroke="%s" stroke-width="1.5"/>`, c, c, radius*0.12, accent)
	b.WriteString(`</svg>`)
	return b.String()
}
