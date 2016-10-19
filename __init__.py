#!/usr/bin/env python
# -*- coding: utf-8 -*-
# dphutils.py
"""
This is for small utility functions that don't have a proper home yet

Copyright (c) 2016, David Hoffman
"""

import numpy as np
import numexpr as ne
import scipy.signal as sig
from scipy.ndimage.fourier import fourier_gaussian
from scipy.signal.signaltools import (_rfft_lock, _rfft_mt_safe,
                                      _inputs_swap_needed, _centered)
from scipy.fftpack.helper import next_fast_len
try:
    import pyfftw
    from pyfftw.interfaces.numpy_fft import (fftshift, ifftshift, fftn, ifftn,
                                             rfftn, irfftn)
    # Turn on the cache for optimum performance
    pyfftw.interfaces.cache.enable()
except ImportError:
    from numpy.fft import (fftshift, ifftshift, fftn, ifftn,
                           rfftn, irfftn)
# import unitary fourier transforms
from .uft import urfftn, uirfftn
eps = np.finfo(float).eps


def scale(data, dtype=None):
    '''
    Scales data to 0 to 1 range

    Examples
    --------
    >>> from numpy.random import randn
    >>> a = randn(10)
    >>> b = scale(a)
    >>> b.max()
    1.0
    >>> b.min()
    0.0
    >>> b = scale(a, dtype = np.uint16)
    >>> b.max()
    65535
    >>> b.min()
    0
    '''

    dmin = np.nanmin(data)
    dmax = np.nanmax(data)

    if dtype is None:
        tmin = 0.0
        tmax = 1.0
    else:
        if np.issubdtype(dtype, np.integer):
            tmin = np.iinfo(dtype).min
            tmax = np.iinfo(dtype).max
        else:
            tmin = np.finfo(dtype).min
            tmax = np.finfo(dtype).max

    return ((data - dmin) / (dmax - dmin) * (tmax - tmin) + tmin).astype(dtype)


def scale_uint16(data):
    '''
    Scales data to uint16 range

    Examples
    --------
    >>> from numpy.random import randn
    >>> a = randn(10)
    >>> a.dtype
    dtype('float64')
    >>> b = scale_uint16(a)
    >>> b.dtype
    dtype('uint16')
    >>> b.max()
    65535
    >>> b.min()
    0
    '''

    return (scale(data) * (2**16 - 1)).astype('uint16')


def radial_profile(data, center=None, binsize=1.0):
    '''
    Take the radial average of a 2D data array

    Taken from http://stackoverflow.com/a/21242776/5030014

    Parameters
    ----------
    data : ndarray (2D)
        the 2D array for which you want to calculate the radial average
    center : sequence
        the center about which you want to calculate the radial average

    Returns
    -------
    radialprofile : ndarray
        a 1D radial average of data

    Examples
    --------
    >>> radial_profile(np.ones((11,11)),(5,5))
    (array([ 1.,  1.,  1.,  1.,  1.,  1.,  1.,  1.]), array([ 0.,  0.,  0.,  0.,  0.,  0.,  0.,  0.]))
    '''
    # test if the data is complex
    if np.iscomplexobj(data):
        # if it is complex, call this function on the real and
        # imaginary parts and return the complex sum.
        real_prof, real_std = radial_profile(np.real(data), center, binsize)
        imag_prof, imag_std = radial_profile(np.imag(data), center, binsize)
        return real_prof + imag_prof * 1j, real_std + imag_std * 1j
    # pull the data shape
    y, x = np.indices((data.shape))
    if center is None:
        # find the center
        center = np.array(data.shape) / 2
    # split the cetner
    y0, x0 = center
    # calculate the radius from center
    r = np.sqrt((x - x0)**2 + (y - y0)**2)
    # convert to int
    r = np.round(r / binsize).astype(np.int)
    # sum the values at equal r
    tbin = np.bincount(r.ravel(), data.ravel())
    # sum the squares at equal r
    tbin2 = np.bincount(r.ravel(), (data**2).ravel())
    # find how many equal r's there are
    nr = np.bincount(r.ravel())
    # calculate the radial mean
    # NOTE: because nr could be zero (for missing bins) the results will
    # have NaN for binsize != 1
    radial_mean = tbin / nr
    # calculate the radial std
    radial_std = np.sqrt(tbin2 / nr - radial_mean**2)
    # return them
    return radial_mean, radial_std


def slice_maker(y0, x0, width):
    '''
    A utility function to generate slices for later use.

    Parameters
    ----------
    y0 : int
        center y position of the slice
    x0 : int
        center x position of the slice
    width : int
        Width of the slice

    Returns
    -------
    slices : list
        A list of slice objects, the first one is for the y dimension and
        and the second is for the x dimension.

    Notes
    -----
    The method will automatically coerce slices into acceptable bounds.

    Examples
    --------
    >>> slice_maker(30,20,10)
    [slice(25, 35, None), slice(15, 25, None)]
    >>> slice_maker(30,20,25)
    [slice(18, 43, None), slice(8, 33, None)]
    '''
    # ensure integers
    y0, x0 = int(y0), int(x0)
    # calculate the start and end
    half1 = width // 2
    # we need two halves for uneven widths
    half2 = width - half1
    ystart = y0 - half1
    xstart = x0 - half1
    yend = y0 + half2
    xend = x0 + half2
    # the max calls are to make slice_maker play nice with edges.
    toreturn = [slice(max(0, ystart), yend), slice(max(0, xstart), xend)]

    # return a list of slices
    return toreturn


def nextpow2(n):
    '''
    Returns the next power of 2 for a given number

    Parameters
    ----------
    n : int
        The number for which you want to know the next power of two

    Returns
    -------
    m : int

    Examples
    --------
    >>> nextpow2(10)
    16
    '''

    if n < 0 or not isinstance(n, int):
        raise ValueError('n must be a positive integer, n = {}'.format(n))

    return 1 << (n - 1).bit_length()


def fft_pad(array, pad_width=None, mode='median', **kwargs):
    '''
    Pad an array to prep it for fft
    '''
    # pull the old shape
    oldshape = array.shape
    if pad_width is None:
        # update each dimenstion to next power of two
        newshape = tuple(nextpow2(n) for n in oldshape)
    else:
        if isinstance(pad_width, int):
            newshape = tuple(pad_width for n in oldshape)
        else:
            newshape = tuple(pad_width)
    # generate pad widths from new shape
    padding = tuple(_calc_pad(o, n) if n is not None else _calc_pad(o, o)
                    for o, n in zip(oldshape, newshape))
    # TODO: add part to deal with cropping here (if padding is negative)
    return np.pad(array, padding, mode=mode, **kwargs)


# add np.pad docstring
fft_pad.__doc__ += np.pad.__doc__


def _calc_pad(oldnum, newnum):
    '''
    We have three cases:
    - old number even new number even
    - old number odd new number even
    - old number odd new number odd
    - old number even new number odd

    >>> _calc_pad(10, 16)
    (3, 3)
    >>> _calc_pad(11, 16)
    (3, 2)
    >>> _calc_pad(11, 17)
    (3, 3)
    >>> _calc_pad(10, 17)
    (4, 3)
    '''

    # how much do we need to add?
    width = newnum - oldnum
    # calculate one side
    pad1 = width // 2
    # calculate the other
    pad2 = width - pad1
    return (pad2, pad1)


def richardson_lucy(image, psf, iterations=10, clip=False, prediction_order=2,
                    win_func=None):
    """
    Richardson-Lucy deconvolution.

    Parameters
    ----------
    image : ndarray
       Input degraded image (can be N dimensional).
    psf : ndarray
       The point spread function.
    iterations : int
       Number of iterations. This parameter plays the role of
       regularisation.
    clip : boolean, optional
       True by default. If true, pixel value of the result above 1 or
       under -1 are thresholded for skimage pipeline compatibility.

    Returns
    -------
    im_deconv : ndarray
       The deconvolved image.

    Examples
    --------
    >>> from skimage import color, data, restoration
    >>> camera = color.rgb2gray(data.camera())
    >>> from scipy.signal import convolve2d
    >>> psf = np.ones((5, 5)) / 25
    >>> camera = convolve2d(camera, psf, 'same')
    >>> camera += 0.1 * camera.std() * np.random.standard_normal(camera.shape)
    >>> deconvolved = restoration.richardson_lucy(camera, psf, 5, False)

    References
    ----------
    .. [1] http://en.wikipedia.org/wiki/Richardson%E2%80%93Lucy_deconvolution
    (2) Biggs, D. S. C.; Andrews, M. Acceleration of Iterative Image Restoration
    Algorithms. Applied Optics 1997, 36 (8), 1766.

    """
    # Stolen from the dev branch of skimage because stable branch is slow
    # checked against matlab on 20160805 and agrees to within machine precision
    image = image.astype(np.float)
    psf = psf.astype(np.float)
    assert psf.ndim == image.ndim, ("image and psf do not have the same number"
                                    " of dimensions")
    if win_func is None:
        window = 1.0
    else:
        winshape = np.array(image.shape)
        winshape[-1] = winshape[-1] // 2 + 1
        window = ifftshift(win_nd(winshape, win_func=win_func))
    # Build the dictionary to pass around and update
    psf_norm = fft_pad(scale(psf), image.shape, mode='constant')
    psf_norm /= psf_norm.sum()
    u_tm2 = None
    u_tm1 = None
    g_tm2 = None
    g_tm1 = None
    u_t = None
    y_t = image
    # below needs to be normalized.
    otf = window * urfftn(ifftshift(psf_norm))

    for i in range(iterations):
        # call the update function
        # make mirror psf
        # calculate RL iteration using the predicted step (y_t)
        reblur = np.real(uirfftn(otf * urfftn(y_t)))
        # assert (reblur > eps).all(), 'Reblur 0 or negative'
        im_ratio = image / reblur
        # assert (im_ratio > eps).all(), 'im_ratio 0 or negative'
        estimate = np.real(uirfftn(np.conj(otf) * urfftn(im_ratio)))
        # assert (estimate > eps).all(), 'im_ratio 0 or negative'
        u_tp1 = y_t * estimate

        # enforce non-negativity
        u_tp1[u_tp1 < 0] = 0

        # update
        u_tm2 = u_tm1
        u_tm1 = u_t
        u_t = u_tp1
        g_tm2 = g_tm1
        g_tm1 = ne.evaluate("u_tp1 - y_t")
        # initialize alpha to zero
        alpha = 0
        # run through the specified iterations
        if i > 1:
            # calculate alpha according to 2
            alpha = (g_tm1 * g_tm2).sum() / (g_tm2**2).sum()

            alpha = max(min(alpha, 1), 0)
            if not np.isfinite(alpha):
                print(alpha)
                alpha = 0
            assert alpha >= 0, alpha
            assert alpha <= 1, alpha

        # if alpha is positive calculate predicted step
        if alpha != 0:
            if prediction_order > 0:
                # first order correction
                h1_t = u_t - u_tm1
                if prediction_order > 1:
                    # second order correction
                    h2_t = (u_t - 2 * u_tm1 + u_tm2)
                else:
                    h2_t = 0
            else:
                h1_t = 0
        else:
            h2_t = 0
            h1_t = 0

        y_t = u_t + alpha * h1_t + alpha**2 / 2 * h2_t
        enusure_positive(y_t)
        assert (y_t >= 0).all()

    im_deconv = u_t

    if clip:
        im_deconv[im_deconv > 1] = 1
        im_deconv[im_deconv < -1] = -1

    return im_deconv


def enusure_positive(a, eps=0):
    '''
    ensure the array is positive with the smallest value equal to eps
    '''
    assert np.isfinite(a).all(), 'The array has NaNs'
    a[a < 0] = eps


def fftconvolve(in1, in2, mode="full", threads=1, win_func=np.ones):

    if in1.ndim == in2.ndim == 0:  # scalar inputs
        return in1 * in2
    elif not in1.ndim == in2.ndim:
        raise ValueError("in1 and in2 should have the same dimensionality")
    elif in1.size == 0 or in2.size == 0:  # empty arrays
        return np.array([])

    s1 = np.array(in1.shape)
    s2 = np.array(in2.shape)
    complex_result = (np.issubdtype(in1.dtype, complex) or
                      np.issubdtype(in2.dtype, complex))
    # shape = s1 + s2 - 1
    # if you double pad the shape, which the above line does then you don't
    # need to take care of any shifting. But you can just pad to the max size
    # and ifftshift one of the inputs.
    shape = np.maximum(s1, s2)
    if _inputs_swap_needed(mode, s1, s2):
        # Convolution is commutative; order doesn't have any effect on output
        in1, s1, in2, s2 = in2, s2, in1, s1

    # Speed up FFT by padding to optimal size for FFTPACK
    fshape = [next_fast_len(int(d)) for d in shape]
    fslice = tuple([slice(0, int(sz)) for sz in shape])
    # Pre-1.9 NumPy FFT routines are not threadsafe.  For older NumPys, make
    # sure we only call rfftn/irfftn from one thread at a time.
    if not complex_result and (_rfft_mt_safe or _rfft_lock.acquire(False)):
        try:
            winshape = np.array(fshape)
            winshape[-1] = winshape[-1] // 2 + 1
            ret = (irfftn(
                rfftn(fft_pad(in1, fshape), threads=threads) *
                rfftn(
                    ifftshift(fft_pad(in2, fshape, mode='constant')),
                    threads=threads) *
                # need to ifftshift the window so that HIGH
                # frequencies are damped, NOT low frequencies
                ifftshift(win_nd(winshape, win_func)), fshape,
                threads=threads)[fslice].copy())
        finally:
            if not _rfft_mt_safe:
                _rfft_lock.release()
    else:
        # If we're here, it's either because we need a complex result, or we
        # failed to acquire _rfft_lock (meaning rfftn isn't threadsafe and
        # is already in use by another thread).  In either case, use the
        # (threadsafe but slower) SciPy complex-FFT routines instead.
        ret = ifftn(fftn(in1, fshape) * fftn(in2, fshape))[fslice].copy()
        if not complex_result:
            ret = ret.real

    if mode == "full":
        return ret
    elif mode == "same":
        return _centered(ret, s1)
    elif mode == "valid":
        return _centered(ret, s1 - s2 + 1)
    else:
        raise ValueError("Acceptable mode flags are 'valid',"
                         " 'same', or 'full'.")


def win_nd(size, win_func=sig.hann, **kwargs):
    '''
    A function to make a multidimensional version of a window function

    Parameters
    ----------
    size : tuple of ints
        size of the output window
    win_func : callable
        Default is the Hanning window
    **kwargs : key word arguments to be passed to win_func

    Returns
    -------
    w : ndarray
        window function
    '''
    ndim = len(size)
    newshapes = tuple([
        tuple([1 if i != j else k for i in range(ndim)])
        for j, k in enumerate(size)])

    # Initialize to return
    toreturn = 1.0

    # cross product the 1D windows together
    for newshape in newshapes:
        toreturn = toreturn * win_func(max(newshape), **kwargs
                                       ).reshape(newshape)

    # return
    return toreturn


def anscombe(data):
    '''
    Apply Anscombe transform to data
    https://en.wikipedia.org/wiki/Anscombe_transform
    '''
    return 2 * np.sqrt(data + 3 / 8)


def anscombe_inv(data):
    '''
    Apply inverse Anscombe transform to data
    https://en.wikipedia.org/wiki/Anscombe_transform
    '''
    part0 = 1 / 4 * data**2
    part1 = 1 / 4 * np.sqrt(3 / 2) / data
    part2 = -11 / 8 / (data**2)
    part3 = 5 / 8 * np.sqrt(3 / 2) / (data**3)
    return part0 + part1 + part2 + part3 - 1 / 8


def fft_gaussian_filter(img, sigma):
    '''
    FFT gaussian convolution

    Parameters
    ----------
    img : ndarray
        Image to convolve with a gaussian kernel
    sigma : int or sequence
        The sigma(s) of the gaussian kernel in _real space_

    Returns
    -------
    filt_img : ndarray
        The filtered image
    '''
    kimg = rfftn(img)
    filt_kimg = fourier_gaussian(kimg, sigma, img.shape[-1])
    return irfftn(filt_kimg)
