import numpy as np
import pytest
from numpy import sin, cos, pi
from numpy.linalg import inv
from numpy.testing import assert_allclose, assert_equal

from panel.iv.covariance import HomoskedasticCovariance, kernel_weight_bartlett, \
    kernel_weight_parzen, kernel_weight_quadratic_spectral, HeteroskedasticCovariance, \
    OneWayClusteredCovariance, KernelCovariance, kernel_optimal_bandwidth, _cov_kernel
from panel.utility import AttrDict


@pytest.fixture(params=['bartlett', 'qs', 'parzen'], scope='module')
def kernel(request):
    kernel_name = request.param
    if kernel_name == 'bartlett':
        weight_func = kernel_weight_bartlett
        alt_names = ['newey-west']
    elif kernel_name == 'parzen':
        weight_func = kernel_weight_parzen
        alt_names = ['gallant']
    else:
        weight_func = kernel_weight_quadratic_spectral
        alt_names = ['quadratic-spectral', 'andrews']
    return AttrDict(kernel=kernel_name, alt_names=alt_names,
                    weight=weight_func)


@pytest.fixture(scope='module')
def data():
    n, k, p = 1000, 5, 3
    np.random.seed(12345)
    clusters = np.random.randint(0, 10, n)
    rho = 0.5
    r = np.zeros((k + p + 1, k + p + 1))
    r.fill(rho)
    r[-1, 2:] = 0
    r[2:, -1] = 0
    r[-1, -1] = 0.5
    r += np.eye(9) * 0.5
    v = np.random.multivariate_normal(np.zeros(r.shape[0]), r, n)
    x = v[:, :k]
    z = v[:, 2:k + p]
    e = v[:, [-1]]
    params = np.arange(1, k + 1) / k
    params = params[:, None]
    y = x @ params + e
    xhat = z @ np.linalg.pinv(z) @ x
    nobs, nvar = x.shape
    s2 = e.T @ e / nobs
    s2_debiased = e.T @ e / (nobs - nvar)
    v = xhat.T @ xhat / nobs
    vinv = inv(v)
    kappa = 0.99
    vk = (x.T @ x * (1 - kappa) + kappa * xhat.T @ xhat) / nobs
    return AttrDict(nobs=nobs, e=e, x=x, y=y, z=z, xhat=xhat,
                    params=params, s2=s2, s2_debiased=s2_debiased,
                    clusters=clusters, nvar=nvar, v=v, vinv=vinv, vk=vk,
                    kappa=kappa)


def test_cov_kernel():
    with pytest.raises(ValueError):
        _cov_kernel(np.arange(100), 1 - np.arange(101) / 101)


def test_kernel_bartlett():
    w = kernel_weight_bartlett(0)
    assert_equal(w, 1 - np.arange(1))
    w = kernel_weight_bartlett(10)
    assert_equal(w, 1 - np.arange(11) / 11)


def test_kernel_parzen():
    def w(k):
        w = np.empty(k + 1)
        for i in range(k + 1):
            z = i / (k + 1)
            if z > 0.5:
                w[i] = 2 * (1 - z ** 3)
            else:
                w[i] = 1 - 6 * z ** 2 + 6 * z ** 3
        return w

    assert_equal(w(0), kernel_weight_parzen(0))
    assert_equal(w(1), kernel_weight_parzen(1))
    assert_equal(w(10), kernel_weight_parzen(10))


def test_kernel_qs():
    def w(k, n):
        w = np.empty(n + 1)
        w[0] = 1
        for i in range(1, n + 1):
            q = 6 * pi * (i / k) / 5
            w[i] = 3 / q ** 2 * (sin(q) / q - cos(q))
        return w

    assert_equal(w(10, 0), kernel_weight_quadratic_spectral(10, 0))
    assert_equal(w(2, 0), kernel_weight_quadratic_spectral(2, 0))
    assert_equal(w(10, 200), kernel_weight_quadratic_spectral(10, 200))
    assert_equal(w(2.5, 200), kernel_weight_quadratic_spectral(2.5, 200))


class TestHomoskedasticCovariance(object):
    def test_asymptotic(self, data):
        c = HomoskedasticCovariance(data.x, data.y, data.z, data.params)
        nobs = data.nobs
        xhat = data.xhat
        s2 = data.s2
        assert c._kappa == 1
        assert c.debiased is False
        assert c.config == {'debiased': False, 'name': 'HomoskedasticCovariance'}
        assert c.s2 == data.s2
        assert_allclose(c.cov, data.s2 * inv(xhat.T @ xhat / nobs) / nobs)
        assert_allclose(c.s, s2 * data.v)
        assert_allclose(c.s, s2 * (xhat.T @ xhat / nobs))

    def test_debiased(self, data):
        c = HomoskedasticCovariance(data.x, data.y, data.z, data.params, True)
        assert c._kappa == 1
        assert c.debiased is True
        assert c.config == {'debiased': True, 'name': 'HomoskedasticCovariance'}
        assert c.s2 == data.s2_debiased
        assert_allclose(c.s, data.s2_debiased * data.v)
        assert_allclose(c.cov, data.s2_debiased * data.vinv / data.nobs)

    def test_kappa(self, data):
        c = HomoskedasticCovariance(data.x, data.y, data.z, data.params, kappa=data.kappa)
        assert c._kappa == 0.99
        assert c.debiased is False
        assert c.config == {'debiased': False, 'name': 'HomoskedasticCovariance'}
        assert_allclose(c.s, data.s2 * data.vk)
        assert_allclose(c.cov, data.s2 * inv(data.vk) / data.nobs)

    def test_kappa_debiased(self, data):
        c = HomoskedasticCovariance(data.x, data.y, data.z, data.params, True, data.kappa)
        assert c._kappa == 0.99
        assert c.debiased is True
        assert c.config == {'debiased': True, 'name': 'HomoskedasticCovariance'}
        assert_allclose(c.s, data.s2_debiased * data.vk)
        assert_allclose(c.cov, data.s2_debiased * inv(data.vk) / data.nobs)

    def test_errors(self, data):
        with pytest.raises(ValueError):
            HomoskedasticCovariance(data.x[:10], data.y, data.z, data.params)
        with pytest.raises(ValueError):
            HomoskedasticCovariance(data.x, data.y, data.z, data.params[1:])


class TestHeteroskedasticCovariance(object):
    def test_asymptotic(self, data):
        c = HeteroskedasticCovariance(data.x, data.y, data.z, data.params)
        assert c._kappa == 1
        assert c.debiased is False
        assert c.config == {'debiased': False, 'name': 'HeteroskedasticCovariance'}
        assert c.s2 == data.s2
        xhat, eps, nobs = data.xhat, data.e, data.nobs
        assert_allclose(c.s, (xhat * eps).T @ (xhat * eps) / nobs)

    def test_debiased(self, data):
        c = HeteroskedasticCovariance(data.x, data.y, data.z, data.params, True)
        xhat, eps, nobs, nvar = data.xhat, data.e, data.nobs, data.nvar
        assert c._kappa == 1
        assert c.debiased is True
        assert c.config == {'debiased': True, 'name': 'HeteroskedasticCovariance'}
        s = (xhat * eps).T @ (xhat * eps) / (nobs - nvar)
        assert_allclose(c.s, s)
        assert_allclose(c.cov, data.vinv @ s @ data.vinv / nobs)

    def test_kappa_debiased(self, data):
        c = HeteroskedasticCovariance(data.x, data.y, data.z, data.params, True, .99)
        assert c._kappa == 0.99
        assert c.debiased is True
        assert c.config == {'debiased': True, 'name': 'HeteroskedasticCovariance'}
        c2 = HeteroskedasticCovariance(data.x, data.y, data.z, data.params, True)
        assert_allclose(c.s, c2.s)
        assert c.s2 == c2.s2
        vk_inv = inv(data.vk)
        assert_allclose(c.cov, vk_inv @ c.s @ vk_inv / data.nobs)

    def test_kappa(self, data):
        c = HeteroskedasticCovariance(data.x, data.y, data.z, data.params, False, .99)
        assert c._kappa == 0.99
        assert c.debiased is False
        assert c.config == {'debiased': False, 'name': 'HeteroskedasticCovariance'}
        c2 = HeteroskedasticCovariance(data.x, data.y, data.z, data.params)
        assert_allclose(c.s, c2.s)
        assert c.s2 == c2.s2
        vk_inv = inv(data.vk)
        assert_allclose(c.cov, vk_inv @ c.s @ vk_inv / data.nobs)


class TestClusteredCovariance(object):
    def test_asymptotic(self, data):
        c = OneWayClusteredCovariance(data.x, data.y, data.z, data.params,
                                      clusters=data.clusters)
        assert c._kappa == 1
        assert c.debiased is False
        assert c.config['debiased'] is False
        assert c.config['name'] == 'OneWayClusteredCovariance'
        assert_equal(c.config['clusters'], data.clusters)
        assert c.s2 == data.s2
        sums = np.zeros((len(np.unique(data.clusters)), data.nvar))
        xe = data.xhat * data.e
        for i in range(len(data.clusters)):
            sums[data.clusters[i]] += xe[i]
        op = np.zeros((data.nvar, data.nvar))
        for j in range(len(sums)):
            op += sums[[j]].T @ sums[[j]]
        s = op / data.nobs
        assert_allclose(c.s, s)
        assert_allclose(c.cov, data.vinv @ s @ data.vinv / data.nobs)

    def test_debiased(self, data):
        c = OneWayClusteredCovariance(data.x, data.y, data.z, data.params,
                                      debiased=True, clusters=data.clusters)
        assert c._kappa == 1
        assert c.debiased is True
        assert c.config['debiased'] is True
        assert c.config['name'] == 'OneWayClusteredCovariance'
        assert_equal(c.config['clusters'], data.clusters)

        ngroups = len(np.unique(data.clusters))
        sums = np.zeros((ngroups, data.nvar))
        xe = data.xhat * data.e
        for i in range(len(data.clusters)):
            sums[data.clusters[i]] += xe[i]
        op = np.zeros((data.nvar, data.nvar))
        for j in range(len(sums)):
            op += sums[[j]].T @ sums[[j]]
        # This is a strange choice
        s = op / data.nobs * ((data.nobs - 1) / (data.nobs - data.nvar)) * ngroups / (ngroups - 1)
        assert_allclose(c.s, s)
        assert_allclose(c.cov, data.vinv @ s @ data.vinv / data.nobs)

    def test_errors(self, data):
        with pytest.raises(ValueError):
            OneWayClusteredCovariance(data.x, data.y, data.z, data.params,
                                      clusters=data.clusters[:10])


class TestKernelBartlettCovariance(object):
    def test_asymptotic(self, data, kernel):
        c = KernelCovariance(data.x, data.y, data.z, data.params,
                             kernel=kernel.kernel)
        for name in kernel.alt_names:
            c2 = KernelCovariance(data.x, data.y, data.z, data.params,
                                  kernel=name)
            assert_equal(c.cov, c2.cov)

        assert c._kappa == 1
        assert c.debiased is False
        assert c.config['debiased'] is False
        assert c.config['name'] == 'KernelCovariance'
        assert_equal(c.config['kernel'], kernel.kernel)
        assert c.s2 == data.s2
        bw = c.config['bandwidth']
        xe = data.xhat * data.e
        s = xe.T @ xe
        w = kernel.weight(bw, xe.shape[0] - 1)
        for i in range(1, len(w)):
            s += w[i] * (xe[i:].T @ xe[:-i] + xe[:-i].T @ xe[i:])
        s /= data.nobs
        assert_allclose(c.s, s)
        assert_allclose(c.cov, data.vinv @ s @ data.vinv / data.nobs)

    def test_debiased(self, data, kernel):
        c = KernelCovariance(data.x, data.y, data.z, data.params,
                             kernel=kernel.kernel, debiased=True)
        for name in kernel.alt_names:
            c2 = KernelCovariance(data.x, data.y, data.z, data.params,
                                  kernel=name, debiased=True)
            assert_equal(c.cov, c2.cov)

        assert c._kappa == 1
        assert c.debiased is True
        assert c.config['debiased'] is True
        assert c.config['name'] == 'KernelCovariance'
        assert_equal(c.config['kernel'], kernel.kernel)
        assert c.s2 == data.s2_debiased

        c2 = KernelCovariance(data.x, data.y, data.z, data.params,
                              kernel=kernel.kernel, debiased=False)
        scale = data.nobs / (data.nobs - data.nvar)
        assert_allclose(c.s, scale * c2.s)
        assert_allclose(c.cov, scale * c2.cov)

    def test_unknown_kernel(self, data, kernel):
        with pytest.raises(ValueError):
            KernelCovariance(data.x, data.y, data.z, data.params,
                             kernel=kernel.kernel + '_unknown')


class TestAutomaticBandwidth(object):
    def test_smoke(self, data, kernel):
        # TODO: This should be improved from a smoke test
        u = data.e.copy()
        for i in range(1, u.shape[0]):
            u[i] = 0.8 * u[i - 1] + data.e[i]
        res = kernel_optimal_bandwidth(u, kernel.kernel)
        assert res > 0

    def test_unknown_kernel(self, data, kernel):
        with pytest.raises(ValueError):
            kernel_optimal_bandwidth(data.e, kernel.kernel + '_unknown')
