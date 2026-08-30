//! A simplified port of Jos Stam's "Stable Fluids" (SIGGRAPH 1999) velocity
//! solver -- the standard unconditionally-stable real-time fluid algorithm,
//! not a bespoke invention. Diffusion is deliberately omitted (a common
//! simplification for decorative real-time backgrounds: at this resolution
//! and frame rate it's visually unnecessary, and skipping it avoids a second
//! Gauss-Seidel relaxation pass every frame): each step is
//! historical-bias -> project -> self-advect -> project, per docs/Memory.md's
//! cursor-flow background pass.
//!
//! Two distinct forces drive the field: `hist_vx`/`hist_vy` is the aggregate
//! cross-visitor cursor field fetched from `/telemetry/flow` (a slow, shared,
//! collective "current"), and `inject()` is the live visitor's own cursor
//! (an immediate, local, individual force). The field is always the sum of
//! both -- no visitor's session ever looks identical to another's, because
//! it's the same shared current perturbed by a different live hand.
//!
//! No wasm-bindgen (see Cargo.toml) -- raw `extern "C"` exports moving flat
//! f32 buffers across the boundary. JS allocates scratch buffers inside this
//! module's own linear memory via `wasm_alloc`, writes into them through a
//! `Float32Array` view, then passes the pointer+length into the exports
//! below. This is the standard "no-bindgen" WASM numeric-kernel pattern, not
//! a workaround specific to this project.

fn ix(w: usize, x: usize, y: usize) -> usize {
    x + y * w
}

fn set_bnd(w: usize, h: usize, b: i32, x: &mut [f32]) {
    for i in 1..w - 1 {
        x[ix(w, i, 0)] = if b == 2 { -x[ix(w, i, 1)] } else { x[ix(w, i, 1)] };
        x[ix(w, i, h - 1)] = if b == 2 { -x[ix(w, i, h - 2)] } else { x[ix(w, i, h - 2)] };
    }
    for j in 1..h - 1 {
        x[ix(w, 0, j)] = if b == 1 { -x[ix(w, 1, j)] } else { x[ix(w, 1, j)] };
        x[ix(w, w - 1, j)] = if b == 1 { -x[ix(w, w - 2, j)] } else { x[ix(w, w - 2, j)] };
    }
    x[ix(w, 0, 0)] = 0.5 * (x[ix(w, 1, 0)] + x[ix(w, 0, 1)]);
    x[ix(w, 0, h - 1)] = 0.5 * (x[ix(w, 1, h - 1)] + x[ix(w, 0, h - 2)]);
    x[ix(w, w - 1, 0)] = 0.5 * (x[ix(w, w - 2, 0)] + x[ix(w, w - 1, 1)]);
    x[ix(w, w - 1, h - 1)] = 0.5 * (x[ix(w, w - 2, h - 1)] + x[ix(w, w - 1, h - 2)]);
}

/// Poisson pressure solve + subtract-gradient, per Stam's method -- makes the
/// field (approximately) divergence-free, which is what turns raw injected
/// forces into swirling, incompressible-looking flow instead of everything
/// just radiating outward from wherever force was added.
fn project(w: usize, h: usize, vx: &mut [f32], vy: &mut [f32], p: &mut [f32], div: &mut [f32]) {
    let n = w.max(h) as f32;
    for j in 1..h - 1 {
        for i in 1..w - 1 {
            let id = ix(w, i, j);
            div[id] = -0.5
                * (vx[ix(w, i + 1, j)] - vx[ix(w, i - 1, j)] + vy[ix(w, i, j + 1)] - vy[ix(w, i, j - 1)])
                / n;
            p[id] = 0.0;
        }
    }
    set_bnd(w, h, 0, div);
    set_bnd(w, h, 0, p);
    for _ in 0..6 {
        for j in 1..h - 1 {
            for i in 1..w - 1 {
                let id = ix(w, i, j);
                p[id] = (div[id] + p[ix(w, i - 1, j)] + p[ix(w, i + 1, j)] + p[ix(w, i, j - 1)] + p[ix(w, i, j + 1)])
                    / 4.0;
            }
        }
        set_bnd(w, h, 0, p);
    }
    for j in 1..h - 1 {
        for i in 1..w - 1 {
            let id = ix(w, i, j);
            vx[id] -= 0.5 * (p[ix(w, i + 1, j)] - p[ix(w, i - 1, j)]) * n;
            vy[id] -= 0.5 * (p[ix(w, i, j + 1)] - p[ix(w, i, j - 1)]) * n;
        }
    }
    set_bnd(w, h, 1, vx);
    set_bnd(w, h, 2, vy);
}

/// Semi-Lagrangian self-advection -- Stam's key "unconditionally stable"
/// trick: trace each cell backward through the CURRENT velocity field and
/// bilinearly sample the previous field there, instead of forward-stepping
/// (which is what makes naive Navier-Stokes solvers blow up at real-time
/// timesteps).
fn advect(w: usize, h: usize, b: i32, d: &mut [f32], d0: &[f32], vx: &[f32], vy: &[f32], dt: f32) {
    let dt0x = dt * (w as f32 - 2.0);
    let dt0y = dt * (h as f32 - 2.0);
    for j in 1..h - 1 {
        for i in 1..w - 1 {
            let id = ix(w, i, j);
            let mut x = i as f32 - dt0x * vx[id];
            let mut y = j as f32 - dt0y * vy[id];
            if x < 0.5 {
                x = 0.5;
            }
            if x > w as f32 - 1.5 {
                x = w as f32 - 1.5;
            }
            let i0 = x as usize;
            let i1 = i0 + 1;
            if y < 0.5 {
                y = 0.5;
            }
            if y > h as f32 - 1.5 {
                y = h as f32 - 1.5;
            }
            let j0 = y as usize;
            let j1 = j0 + 1;
            let s1 = x - i0 as f32;
            let s0 = 1.0 - s1;
            let t1 = y - j0 as f32;
            let t0 = 1.0 - t1;
            d[id] = s0 * (t0 * d0[ix(w, i0, j0)] + t1 * d0[ix(w, i0, j1)])
                + s1 * (t0 * d0[ix(w, i1, j0)] + t1 * d0[ix(w, i1, j1)]);
        }
    }
    set_bnd(w, h, b, d);
}

pub struct FluidSim {
    w: usize,
    h: usize,
    vx: Vec<f32>,
    vy: Vec<f32>,
    vx0: Vec<f32>,
    vy0: Vec<f32>,
    hist_vx: Vec<f32>,
    hist_vy: Vec<f32>,
}

impl FluidSim {
    fn new(w: usize, h: usize) -> FluidSim {
        let n = w * h;
        FluidSim {
            w,
            h,
            vx: vec![0.0; n],
            vy: vec![0.0; n],
            vx0: vec![0.0; n],
            vy0: vec![0.0; n],
            hist_vx: vec![0.0; n],
            hist_vy: vec![0.0; n],
        }
    }

    fn set_historical(&mut self, vx: &[f32], vy: &[f32]) {
        let n = self.w * self.h;
        let m = n.min(vx.len()).min(vy.len());
        self.hist_vx[..m].copy_from_slice(&vx[..m]);
        self.hist_vy[..m].copy_from_slice(&vy[..m]);
    }

    fn inject(&mut self, nx: f32, ny: f32, dvx: f32, dvy: f32, radius: f32) {
        let cx = (nx * self.w as f32) as i32;
        let cy = (ny * self.h as f32) as i32;
        let r = radius.max(1.0) as i32;
        for oy in -r..=r {
            for ox in -r..=r {
                let x = cx + ox;
                let y = cy + oy;
                if x < 1 || y < 1 || x as usize >= self.w - 1 || y as usize >= self.h - 1 {
                    continue;
                }
                let d2 = (ox * ox + oy * oy) as f32;
                let falloff = (-d2 / ((r * r) as f32 + 1.0)).exp();
                let id = ix(self.w, x as usize, y as usize);
                self.vx[id] += dvx * falloff;
                self.vy[id] += dvy * falloff;
            }
        }
    }

    fn step(&mut self, dt: f32, historical_strength: f32) {
        let n = self.w * self.h;
        for i in 0..n {
            self.vx[i] += (self.hist_vx[i] - self.vx[i]) * historical_strength * dt;
            self.vy[i] += (self.hist_vy[i] - self.vy[i]) * historical_strength * dt;
        }

        project(self.w, self.h, &mut self.vx, &mut self.vy, &mut self.vx0, &mut self.vy0);

        self.vx0.copy_from_slice(&self.vx);
        self.vy0.copy_from_slice(&self.vy);
        let vx0 = self.vx0.clone();
        let vy0 = self.vy0.clone();
        advect(self.w, self.h, 1, &mut self.vx, &vx0, &vx0, &vy0, dt);
        advect(self.w, self.h, 2, &mut self.vy, &vy0, &vx0, &vy0, dt);

        project(self.w, self.h, &mut self.vx, &mut self.vy, &mut self.vx0, &mut self.vy0);
    }
}

// ---------------------------------------------------------------------------
// Raw C ABI surface. `sim` pointers are opaque to JS -- it only ever stores
// and passes back what `fluid_new` returned, never dereferences it.
// ---------------------------------------------------------------------------

#[no_mangle]
pub extern "C" fn fluid_new(w: usize, h: usize) -> *mut FluidSim {
    Box::into_raw(Box::new(FluidSim::new(w, h)))
}

#[no_mangle]
pub extern "C" fn fluid_free(sim: *mut FluidSim) {
    if !sim.is_null() {
        unsafe { drop(Box::from_raw(sim)) };
    }
}

/// Scratch allocator so JS can get a pointer INTO this module's own linear
/// memory to write floats into (e.g. the resampled historical field) before
/// calling a function that reads from that pointer. Never freed individually
/// -- callers reuse the same handful of scratch buffers for the module's
/// lifetime, so there's no allocator churn to manage.
#[no_mangle]
pub extern "C" fn wasm_alloc(len: usize) -> *mut f32 {
    let mut buf = vec![0.0f32; len];
    let ptr = buf.as_mut_ptr();
    core::mem::forget(buf);
    ptr
}

#[no_mangle]
pub extern "C" fn fluid_set_historical(sim: *mut FluidSim, vx_ptr: *const f32, vy_ptr: *const f32, len: usize) {
    let sim = unsafe { &mut *sim };
    let vx = unsafe { core::slice::from_raw_parts(vx_ptr, len) };
    let vy = unsafe { core::slice::from_raw_parts(vy_ptr, len) };
    sim.set_historical(vx, vy);
}

#[no_mangle]
pub extern "C" fn fluid_inject(sim: *mut FluidSim, nx: f32, ny: f32, dvx: f32, dvy: f32, radius: f32) {
    let sim = unsafe { &mut *sim };
    sim.inject(nx, ny, dvx, dvy, radius);
}

#[no_mangle]
pub extern "C" fn fluid_step(sim: *mut FluidSim, dt: f32, historical_strength: f32) {
    let sim = unsafe { &mut *sim };
    sim.step(dt, historical_strength);
}

#[no_mangle]
pub extern "C" fn fluid_vx_ptr(sim: *mut FluidSim) -> *const f32 {
    let sim = unsafe { &*sim };
    sim.vx.as_ptr()
}

#[no_mangle]
pub extern "C" fn fluid_vy_ptr(sim: *mut FluidSim) -> *const f32 {
    let sim = unsafe { &*sim };
    sim.vy.as_ptr()
}

#[no_mangle]
pub extern "C" fn fluid_len(sim: *mut FluidSim) -> usize {
    let sim = unsafe { &*sim };
    sim.w * sim.h
}
