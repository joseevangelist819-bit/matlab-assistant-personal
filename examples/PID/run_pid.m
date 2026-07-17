root=fileparts(mfilename('fullpath'));
plant=tf(1,[1 2 1]); controller=pidtune(plant,'PID'); closed_loop=feedback(controller*plant,1);
[y,t]=step(closed_loop,0:0.01:10); info=stepinfo(y,t); stable=isstable(closed_loop);
result=struct('Kp',controller.Kp,'Ki',controller.Ki,'Kd',controller.Kd,'stable',stable,'overshoot',info.Overshoot,'settling_time',info.SettlingTime,'final_value',y(end));
save(fullfile(root,'result.mat'),'result','t','y','controller','plant');
figure('Visible','off');plot(t,y,'LineWidth',1.4);grid on;title('PID Closed Loop');exportgraphics(gcf,fullfile(root,'result.png'));close(gcf);
