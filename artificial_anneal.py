import numpy as np
from matplotlib import pyplot as plt
from scipy.optimize import approx_fprime, minimize
from scipy.interpolate import RectBivariateSpline, UnivariateSpline
import os
from termcolor import cprint

class ConvergenceMonitor:
    def __init__(self, Uopt, grad_Uopt, N, Uext=None, xext=None, yext=None, verbose=True, eps=1E-12, save_path=None,
                 figsize=(12.,3.), coordinate_transformation=None):
        """
        To be used with scipy.optimize.minimize as a call back function. One has two choices for call-back functions:
        - monitor_convergence: print the status of convergence (value of Uopt and norm of grad_Uopt)
        - save_pictures: save figures of the electron positions every iteration to construct a movie.
        :param Uopt: Cost function or total energy of the system. Uopt takes one argument and returns a scalar.
        :param grad_Uopt: Gradient of Uopt. This should be a function that takes one argument and returns
                          an array of size 2*N_electrons
        :param N: Report the status of optimization every N times. This should be an integer
        :param Uext: Electrostatic potential function. Takes 2 arguments (x,y) and returns an array of the size of x
        and y
        :param xext: Array of arbitrary size for evaluating the electrostatic potential. Units should be meters.
        :param yext: Array of arbitrary size for evaluating the electrostatic potential. Units should be meters.
        :param verbose: Whether to print the status when monitor_convergence is called.
        :param eps: Step size used to numerically approximate the gradient with scipy.optimize.approx_fprime
        :param save_path: Directory in which to save figures when self.save_pictures is called. None by default.
        """
        self.call_every = N
        self.call_counter = 0
        self.verbose = verbose
        self.curr_grad_norm = list()
        self.curr_fun = list()
        self.iter = list()
        self.epsilon = eps
        self.save_path = save_path
        self.Uopt = Uopt
        self.grad_Uopt = grad_Uopt
        self.xext, self.yext, self.Uext = xext, yext, Uext
        self.figsize = figsize
        self.coordinate_transformation = coordinate_transformation

    def monitor_convergence(self, xk):
        """
        Monitor the convergence while the optimization is running. To be used with scipy.optimize.minimize.
        :param xk: Electron position pairs
        :return: None
        """
        if not (self.call_counter % self.call_every):
            self.iter.append(self.call_counter)
            self.curr_fun.append(self.Uopt(xk))
            # Here we use the L-inf norm (the maximum)
            self.curr_grad_norm.append(np.max(np.abs(self.grad_Uopt(xk))))

            if self.call_counter == 0:
                self.jac = self.grad_Uopt(xk)
                self.approx_fprime = approx_fprime(xk, self.Uopt, self.epsilon)
            else:
                self.jac = np.vstack((self.jac, self.grad_Uopt(xk)))
                self.approx_fprime = np.vstack((self.approx_fprime, approx_fprime(xk, self.Uopt, self.epsilon)))

            if self.verbose:
                print("%d\tUopt: %.8f eV\tNorm of gradient: %.2e eV/m" \
                      % (self.call_counter, self.curr_fun[-1], self.curr_grad_norm[-1]))

        self.call_counter += 1

    def save_pictures(self, xk):
        """
        Plots the current value of the electron position array xk and saves a picture in self.save_path.
        :param xk: Electron position pairs
        :return: None
        """
        xext, yext = self.xext, self.yext
        Uext = self.Uext

        fig = plt.figure(figsize=self.figsize)
        try:
            common.configure_axes(12)
        except:
            pass

        if (Uext is not None) and (xext is not None) and (yext is not None):
            Xext, Yext = np.meshgrid(xext, yext)
            plt.pcolormesh(xext * 1E6, yext * 1E6, Uext(Xext, Yext), cmap=plt.cm.Spectral_r, vmax=0.0)
            plt.xlim(np.min(xext) * 1E6, np.max(xext) * 1E6)
            plt.ylim(np.min(yext) * 1E6, np.max(yext) * 1E6)

        if self.coordinate_transformation is None:
            electrons_x, electrons_y = xk[::2], xk[1::2]
        else:
            r_new = self.coordinate_transformation(xk)
            electrons_x, electrons_y = r2xy(r_new)

        plt.plot(electrons_x*1E6, electrons_y*1E6, 'o', color='deepskyblue')
        plt.xlabel("$x$ ($\mu$m)")
        plt.ylabel("$y$ ($\mu$m)")
        plt.colorbar()

        if self.save_path is not None:
            fig.savefig(os.path.join(self.save_path, '%.5d.png' % (self.call_counter)), bbox_inches='tight', dpi=300)
        else:
            print("Please specify a save path when initiating ConvergenceMonitor")

        plt.close('all')

        self.monitor_convergence(xk)

    def create_movie(self, fps, filenames_in="%05d.png", filename_out="movie.mp4"):
        """
        Generate a movie from the pictures generated by save_pictures. Movie gets saved in self.save_path
        For filenames of the type 00000.png etc use filenames_in="%05d.png".
        Files must all have the save extension and resolution.
        :param fps: frames per second (integer).
        :param filenames_in: Signature of series of file names in Unix style. Ex: "%05d.png"
        :param filename_out: File name of the output video. Ex: "movie.mp4"
        :return: None
        """
        curr_dir = os.getcwd()
        os.chdir(self.save_path)
        os.system(r"ffmpeg -r {} -b 1800 -i {} {}".format(int(fps), filenames_in, filename_out))
        os.chdir(curr_dir)

class ElectrostaticPotential:

    def __init__(self, grid_data_x, grid_data_y, potential_data, spline_order_x=3, spline_order_y=3, smoothing=0):
        """
        This class is used for constructing the functional forms required for scipy.optimize.minimize.
        It deals with the Maxwell input data, as well as constructs the cost function used in the optimizer.
        It also calculates the gradient, that can be used to speed up the optimizer.
        :param grid_data_x: 1D array of x-data. Coordinates from grid_data_x & grid_data_y must form a rectangular grid
        :param grid_data_y: 1D array of y-data. Coordinates from grid_data_x & grid_data_y must form a rectangular grid
        :param potential_data: Energy land scape, - e V_ext.
        :param spline_order_x: Order of the interpolation in the x-direction (1 = linear, 3 = cubic)
        :param spline_order_y: Order of the interpolation in the y-direction (1 = linear, 3 = cubic)
        :param smoothing: Absolute smoothing. Effect depends on scale of potential_data.
        """
        self.interpolator = RectBivariateSpline(grid_data_x, grid_data_y, potential_data,
                                                kx=spline_order_x, ky=spline_order_y, s=smoothing)

        # Constants
        self.qe = 1.602E-19
        self.eps0 = 8.85E-12

    def V(self, xi, yi):
        """
        Evaluate the electrostatic potential at coordinates xi, yi
        :param xi: a 1D array, or float
        :param yi: a 1D array or float
        :return: Interpolated value(s) of the data supplied to __init__ at values (xi, yi)
        """
        return self.interpolator.ev(xi, yi)

    def Velectrostatic(self, xi, yi):
        """
        When supplying two arrays of size n to V, it returns an array
        of size nxn, according to the meshgrid it has evaluated. We're only interested
        in the sum of the diagonal elements, so we take the sum and this represents
        the sum of the static energy of the n particles in the potential.
        :param xi: a 1D array, or float
        :param yi: a 1D array or float
        """
        return self.qe * np.sum(self.V(xi, yi))

    def Vee(self, xi, yi, eps=1E-15):
        """
        Returns the repulsion potential between two electrons separated by a distance sqrt(|xi-xj|**2 + |yi-yj|**2)
        Note the factor 1/2. in front of the potential energy to avoid overcounting.
        :param xi: a 1D array, or float
        :param yi: a 1D array or float
        """
        Xi, Yi = np.meshgrid(xi, yi)
        Xj, Yj = Xi.T, Yi.T

        Rij = np.sqrt((Xi - Xj) ** 2 + (Yi - Yj) ** 2)
        np.fill_diagonal(Rij, eps)

        return + 1 / 2. * self.qe ** 2 / (4 * np.pi * self.eps0) * 1 / Rij

    def Vtotal(self, r):
        """
        This can be used as a cost function for the optimizer.
        Returns the total energy of N electrons
        r is a 0D array with coordinates of the electrons.
        The x-coordinates are thus given by the even elements of r: r[::2],
        whereas the y-coordinates are the odd ones: r[1::2]
        :param r: r = np.array([x0, y0, x1, y1, x2, y2, ... , xN, yN])
        :return: Scalar with the total energy of the system.
        """
        xi, yi = r[::2], r[1::2]
        Vtot = self.Velectrostatic(xi, yi)
        interaction_matrix = self.Vee(xi, yi)
        np.fill_diagonal(interaction_matrix, 0)
        Vtot += np.sum(interaction_matrix)
        return Vtot / self.qe

    def dVdx(self, xi, yi):
        """
        Derivative of the electrostatic potential in the x-direction.
        :param xi: a 1D array, or float
        :param yi: a 1D array or float
        :return:
        """
        return self.interpolator.ev(xi, yi, dx=1, dy=0)

    def ddVdx(self, xi, yi):
        """
        Second derivative of the electrostatic potential in the x-direction.
        :param xi: a 1D array, or float
        :param yi: a 1D array or float
        :return:
        """
        return self.interpolator.ev(xi, yi, dx=2, dy=0)

    def dVdy(self, xi, yi):
        """
        Derivative of the electrostatic potential in the y-direction
        :param xi: a 1D array, or float
        :param yi: a 1D array or float
        :return:
        """
        return self.interpolator.ev(xi, yi, dx=0, dy=1)

    def ddVdy(self, xi, yi):
        """
        Second derivative of the electrostatic potential in the y-direction.
        :param xi: a 1D array, or float
        :param yi: a 1D array or float
        :return:
        """
        return self.interpolator.ev(xi, yi, dx=0, dy=2)

    def grad_Vee(self, xi, yi, eps=1E-15):
        """
        Derivative of the electron-electron interaction term
        :param xi: a 1D array, or float
        :param yi: a 1D array or float
        :param eps: A small but non-zero number to avoid triggering Warning message. Exact value is irrelevant.
        :return: 1D-array of size(xi) + size(yi)
        """
        Xi, Yi = np.meshgrid(xi, yi)
        Xj, Yj = Xi.T, Yi.T

        Rij = np.sqrt((Xi - Xj) ** 2 + (Yi - Yj) ** 2)
        np.fill_diagonal(Rij, eps)

        gradx_matrix = np.zeros(np.shape(Rij))
        grady_matrix = np.zeros(np.shape(Rij))
        gradient = np.zeros(2 * len(xi))

        gradx_matrix = -1 * self.qe ** 2 / (4 * np.pi * self.eps0) * (Xi - Xj) / Rij ** 3
        np.fill_diagonal(gradx_matrix, 0)

        grady_matrix = +1 * self.qe ** 2 / (4 * np.pi * self.eps0) * (Yi - Yj) / Rij ** 3
        np.fill_diagonal(grady_matrix, 0)

        gradient[::2] = np.sum(gradx_matrix, axis=0)
        gradient[1::2] = np.sum(grady_matrix, axis=0)

        return gradient

    def grad_total(self, r):
        """
        Total derivative of the cost function. This may be used in the optimizer to converge faster.
        :param r: r = np.array([x0, y0, x1, y1, x2, y2, ... , xN, yN])
        :return: 1D array of length len(r)
        """
        xi, yi = r[::2], r[1::2]
        gradient = np.zeros(len(r))
        gradient[::2] = self.dVdx(xi, yi)
        gradient[1::2] = self.dVdy(xi, yi)
        gradient += self.grad_Vee(xi, yi) / self.qe
        return gradient

class PostProcess:
    def __init__(self, save_path=None):
        """
        Post process the results after the optimizer has converged.
        :param save_path: Directory in which to save figures/movies.
        """
        self.save_path = save_path
        self.trapped_electrons = None

    def get_electron_density(self, r, verbose=True):
        """
        Calculate the electron density based on the nearest neighbor for each electron. The electron density is in m^-2
        :param r: Electron x,y coordinate pairs
        :param verbose: Whether to print the result or just to return it
        :return: Electron density in m^-2
        """
        xi, yi = r2xy(r)
        Xi, Yi = np.meshgrid(xi, yi)
        Xj, Yj = Xi.T, Yi.T

        Rij = np.sqrt((Xi - Xj) ** 2 + (Yi - Yj) ** 2)
        np.fill_diagonal(Rij, 1E10)

        nearest_neighbors = np.min(Rij, axis=1)
        ns = 1 / (np.mean(nearest_neighbors)) ** 2
        if verbose:
            print("The electron density in the figure above is %.3e m^-2" % ns)

        return ns

    def save_snapshot(self, r, xext=None, yext=None, Uext=None, figsize=(12.,3.), clim=(-1,0), common=None, title=""):
        """
        Save a picture with the electron positions on top of the electrostatic potential data.
        :param r: Electron x,y coordinate pairs
        :param xext: x-data (1D-array) for plotting the electrostatic potential
        :param yext: y-data (1D-array) for plotting the electrostatic potential
        :param Uext: Potential function for plotting the electrostatic potential
        :param figsize: Tuple that regulates the figure size
        :param common: module that allows saving
        :return: None
        """
        fig = plt.figure(figsize=figsize)

        if common is not None:
            common.configure_axes(12)

        if (Uext is not None) and (xext is not None) and (yext is not None):
            Xext, Yext = np.meshgrid(xext, yext)
            plt.pcolormesh(xext * 1E6, yext * 1E6, Uext(Xext, Yext), cmap=plt.cm.Spectral_r,
                           vmax=clim[1], vmin=clim[0])
            plt.xlim(np.min(xext) * 1E6, np.max(xext) * 1E6)
            plt.ylim(np.min(yext) * 1E6, np.max(yext) * 1E6)

        plt.plot(r[::2] * 1E6, r[1::2] * 1E6, 'o', color='deepskyblue')
        plt.xlabel("$x$ ($\mu$m)")
        plt.ylabel("$y$ ($\mu$m)")
        plt.colorbar()
        plt.title(title)

        if self.save_path is not None and common is not None:
            common.save_figure(fig, save_path=self.save_path)
        else:
            print("Please specify a save path when initiating PostProcess")

        plt.close('all')

    def write2file(self, **kwargs):
        """
        Write simulation results to an npz file in self.save_path
        :param kwargs: Dictionary of parameters to be saved to the file.
        :return: None
        """

        number = 0
        file_name = "%.5d.npz"%number

        while file_name in os.listdir(self.save_path):
            file_name = "%.5d.npz"%(number)
            number += 1

        #print("Saving file to %s ..."%(os.path.join(self.save_path, file_name)))

        np.savez(os.path.join(self.save_path, file_name), **kwargs)

    def get_trapped_electrons(self, r, trap_area_x=(-4E-6, -1.8E-6)):
        """
        Evaluate how many electrons are in the area specified by the bounds trap_area_x[0] < x < trap_area_x[1]
        :param r: r = np.array([x0, y0, x1, y1, x2, y2, ... , xN, yN])
        :param trap_area_x: Tuple specifying the bounds of the trapping area
        :return: The number of electrons in the trapping area (scalar)
        """
        return len(np.where(np.logical_and(r[::2] > trap_area_x[0], r[::2] < trap_area_x[1]))[0])

class ResonatorSolver:

    def __init__(self, grid_data, potential_data, efield_data=None, box_length=40E-6, spline_order_x=3, smoothing=0):
        self.interpolator = UnivariateSpline(grid_data, potential_data, k=spline_order_x, s=smoothing, ext=3)
        self.derivative = self.interpolator.derivative(n=1)
        self.second_derivative = self.interpolator.derivative(n=2)
        self.box_y_length = box_length

        # Constants
        self.qe = 1.602E-19
        self.eps0 = 8.85E-12

        if efield_data is not None:
            self.Ex_interpolator = UnivariateSpline(grid_data, efield_data, k=spline_order_x, s=smoothing, ext=3)

    def map_y_into_domain(self, y, ybounds=None):
        if ybounds is None:
            ybounds = (-self.box_y_length / 2, self.box_y_length / 2)
        return ybounds[0] + (y - ybounds[0]) % (ybounds[1] - ybounds[0])

    def calculate_Rij(self, xi, yi):
        Xi, Yi = np.meshgrid(xi, yi)
        Xj, Yj = Xi.T, Yi.T

        Rij_standard = np.sqrt((Xi - Xj) ** 2 + (Yi - Yj) ** 2)

        Yi_shifted = Yi.copy()
        Yi_shifted[Yi_shifted > 0] -= self.box_y_length  # Shift entire box length
        Yj_shifted = Yi_shifted.T

        Rij_shifted = np.sqrt((Xi - Xj) ** 2 + (Yi_shifted - Yj_shifted) ** 2)

        return np.minimum(Rij_standard, Rij_shifted)

    def calculate_YiYj(self, xi, yi):
        Xi, Yi = np.meshgrid(xi, yi)
        Xj, Yj = Xi.T, Yi.T

        Yi_shifted = Yi.copy()
        Yi_shifted[Yi_shifted > 0] -= self.box_y_length  # Shift entire box length
        Yj_shifted = Yi_shifted.T

        Rij_standard = np.sqrt((Xi - Xj) ** 2 + (Yi - Yj) ** 2)
        Rij_shifted = np.sqrt((Xi - Xj) ** 2 + (Yi_shifted - Yj_shifted) ** 2)

        YiYj = Yi - Yj
        YiYj_shifted = Yi_shifted - Yj_shifted

        # Use shifted y-coordinate only in this case:
        np.copyto(YiYj, YiYj_shifted, where=Rij_shifted<Rij_standard)

        return YiYj

    def Ex(self, xi, yi):
        return self.Ex_interpolator(xi)

    def V(self, xi, yi):
        return self.interpolator(xi)

    def Velectrostatic(self, xi, yi):
        return self.qe * np.sum(self.V(xi, yi))

    def Vee(self, xi, yi, eps=1E-15):
        yi = self.map_y_into_domain(yi)
        Rij = self.calculate_Rij(xi, yi)
        np.fill_diagonal(Rij, eps)

        return + 1 / 2. * self.qe ** 2 / (4 * np.pi * self.eps0) * 1 / Rij

    def Vtotal(self, r):
        xi, yi = r[::2], r[1::2]
        Vtot = self.Velectrostatic(xi, yi)
        interaction_matrix = self.Vee(xi, yi)
        np.fill_diagonal(interaction_matrix, 0)
        Vtot += np.sum(interaction_matrix)
        return Vtot / self.qe

    def dVdx(self, xi, yi):
        return self.derivative(xi)

    def ddVdx(self, xi, yi):
        return self.second_derivative(xi)

    def dVdy(self, xi, yi):
        return np.zeros(len(xi))

    def ddVdy(self, xi, yi):
        return np.zeros(len(xi))

    def grad_Vee(self, xi, yi, eps=1E-15):
        yi = self.map_y_into_domain(yi)
        Xi, Yi = np.meshgrid(xi, yi)
        Xj, Yj = Xi.T, Yi.T

        Rij = self.calculate_Rij(xi, yi)
        np.fill_diagonal(Rij, eps)

        gradx_matrix = np.zeros(np.shape(Rij))
        grady_matrix = np.zeros(np.shape(Rij))
        gradient = np.zeros(2 * len(xi))

        gradx_matrix = -1 * self.qe ** 2 / (4 * np.pi * self.eps0) * (Xi - Xj) / Rij ** 3
        np.fill_diagonal(gradx_matrix, 0)

        YiYj = self.calculate_YiYj(xi, yi)
        grady_matrix = +1 * self.qe ** 2 / (4 * np.pi * self.eps0) * YiYj / Rij ** 3
        np.fill_diagonal(grady_matrix, 0)

        gradient[::2] = np.sum(gradx_matrix, axis=0)
        gradient[1::2] = np.sum(grady_matrix, axis=0)

        return gradient

    def grad_total(self, r):
        """
        Total derivative of the cost function. This may be used in the optimizer to converge faster.
        :param r: r = np.array([x0, y0, x1, y1, x2, y2, ... , xN, yN])
        :return: 1D array of length len(r)
        """
        xi, yi = r[::2], r[1::2]
        gradient = np.zeros(len(r))
        gradient[::2] = self.dVdx(xi, yi)
        gradient[1::2] = self.dVdy(xi, yi)
        gradient += self.grad_Vee(xi, yi) / self.qe
        return gradient

    def thermal_kick_x(self, x, y, T):
        kB = 1.38E-23
        qe = 1.602E-19
        ktrapx = np.abs(qe * self.ddVdx(x, y))
        return np.sqrt(2 * kB * T / ktrapx)

    def perturb_and_solve(self, cost_function, N_perturbations, T, solution_data_reference, **kwargs):

        electron_initial_positions = solution_data_reference['x']
        best_result = solution_data_reference

        for n in range(N_perturbations):
            xi, yi = r2xy(electron_initial_positions)
            xi_prime = xi + self.thermal_kick_x(xi, yi, T) * np.random.randn(len(xi))
            yi_prime = yi + self.thermal_kick_x(xi, yi, T) * np.random.randn(len(yi))
            electron_perturbed_positions = xy2r(xi_prime, yi_prime)

            res = minimize(cost_function, electron_perturbed_positions, method='CG', **kwargs)

            if res['status'] == 0 and res['fun'] < best_result['fun']:
                cprint("New minimum was found after perturbing!", "green")
                best_result = res
            elif res['status'] == 0 and res['fun'] > best_result['fun']:
                pass  # No new minimum was found after perturbation, this is quite common.
            elif res['status'] != 0 and res['fun'] < best_result['fun']:
                cprint("There is a lower state, but minimizer didn't converge!", "red")
            elif res['status'] != 0 and res['fun'] > best_result['fun']:
                cprint("Minimizer didn't converge, but this is not the lowest energy state!", "magenta")

        return best_result

######################
## HELPER FUNCTIONS ##
######################

def r2xy(r):
    """
    Reformat electron position array.
    :param r: r = np.array([x0, y0, x1, y1, x2, y2, ... , xN, yN])
    :return: np.array([x0, x1, ...]), np.array([y0, y1, ...])
    """
    return r[::2], r[1::2]

def xy2r(x, y):
    """
    Reformat electron position array.
    :param x: np.array([x0, x1, ...])
    :param y: np.array([y0, y1, ...])
    :return: r = np.array([x0, y0, x1, y1, x2, y2, ... , xN, yN])
    """
    if len(x) == len(y):
        r = np.zeros(2 * len(x))
        r[::2] = x
        r[1::2] = y
        return r
    else:
        raise ValueError("x and y must have the same length!")

def map_into_domain(xi, yi, xbounds=(-1,1), ybounds=(-1,1)):
    """
    If electrons leave the simulation box, it may be desirable to map them back into the domain. If the electrons cross
    the right boundary, they will be mirrored and their mapped position is returned.
    :param xi: np.array([x0, x1, ...])
    :param yi: np.array([y0, y1, ...])
    :param xbounds: Tuple specifying the bounds in the x-direction
    :param ybounds: Tuple specifying the bounds in the y-direction
    :return: xi, yi (all within the simulation box)
    """
    left_boundary, right_boundary = xbounds
    bottom_boundary, top_boundary = ybounds

    L = right_boundary - left_boundary
    W = top_boundary - bottom_boundary

    xi = np.abs(L - (xi - right_boundary) % (2 * L)) + left_boundary
    yi[yi>top_boundary] = top_boundary
    yi[yi<bottom_boundary] = bottom_boundary

    return xi, yi

def thermal_kick_y(x, y, T):
    kB = 1.38E-23
    qe = 1.602E-19
    ktrapy = np.abs(qe * EP.ddVdy(xi=x, yi=y))
    return np.sqrt(2 * kB * T / ktrapy)