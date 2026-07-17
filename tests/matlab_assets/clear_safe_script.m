clear;
x = 1:5;
y = x.^2;
save(fullfile(fileparts(mfilename('fullpath')), 'clear_safe_output.mat'), 'x', 'y');
